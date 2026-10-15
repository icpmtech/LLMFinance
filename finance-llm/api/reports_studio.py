"""Estúdio de relatórios — criação de relatórios por administradores e gestores.

O módulo «Relatórios» vende relatórios produzidos pela equipa. O **Estúdio** é a
oficina onde essa equipa os monta: escolhe um **modelo**, junta **blocos**
(indicadores, gráficos, tabelas, grafos e texto) sobre as **fontes** de dados da
plataforma (os mesmos datasets do Visualizador), pede ajuda à **IA** para o
sumário e para os destaques, gera o **PDF** e publica-o — na plataforma
(*site*) ou na loja — com preço.

Como tudo se liga:

* **Fontes** — vêm do catálogo do Visualizador (`visualizador_service`), pelo que
  as agregações são as mesmas das páginas: não há uma segunda implementação dos
  números. Um bloco guarda `source`, `dimensions`, `measures` e `filters`; os
  ids são validados contra o catálogo no momento de gravar (e outra vez ao
  desenhar), porque a ontologia muda.
* **Publicação no site** — o relatório passa a ser um pacote do catálogo de
  relatórios (`reports_store.save_package`) com `auto = "estudio:<id>"`: o cliente
  pede e paga como qualquer outro pacote e o PDF é gerado sem passar pela equipa.
* **Publicação na loja** — cria (ou atualiza) um produto digital na loja com
  `auto_report = "estudio:<id>"`: pago o pedido, o PDF é anexado à encomenda.

O ficheiro do estúdio é o mesmo documento dos relatórios
(`data/reports/reports.json`), na chave `studio_reports`; os PDFs ficam em
`data/reports/studio/<relatório>/`.
"""
from __future__ import annotations

import copy
import logging
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import reports_store as store

logger = logging.getLogger(__name__)

STUDIO_DIR = store.REPORTS_DIR / "studio"

REPORT_STATUSES: Tuple[str, ...] = ("rascunho", "publicado")
REPORT_LABELS: Dict[str, str] = {"rascunho": "Rascunho", "publicado": "Publicado"}
REPORT_STYLE: Dict[str, str] = {"rascunho": "amber", "publicado": "emerald"}

#: Canais de publicação. `site` = catálogo de relatórios da plataforma;
#: `loja` = produto digital na loja.
TARGETS: Tuple[str, ...] = ("site", "loja")
TARGET_LABELS: Dict[str, str] = {"site": "Plataforma (catálogo de relatórios)", "loja": "Loja"}

BLOCK_TYPES: Tuple[str, ...] = ("heading", "text", "note", "ai", "kpi", "chart", "table", "graph", "empresa", "web")
BLOCK_LABELS: Dict[str, str] = {
    "heading": "Secção",
    "text": "Texto",
    "note": "Nota metodológica",
    "ai": "Texto com IA",
    "kpi": "Indicadores",
    "chart": "Gráfico",
    "table": "Tabela",
    "graph": "Grafo de relações",
    "empresa": "Ficha da empresa (360)",
    "web": "Produtos e serviços (pesquisa web)",
}
BLOCK_HINTS: Dict[str, str] = {
    "heading": "Abre um capítulo do relatório.",
    "text": "Texto escrito por quem monta o relatório.",
    "note": "Rodapé de método, fonte e limites do que se apresenta.",
    "ai": "Texto redigido pela IA a partir dos dados do relatório (com alternativa factual).",
    "kpi": "Até 4 indicadores de uma fonte (contagem, soma, média…).",
    "chart": "Gráfico de barras, linhas, área ou circular sobre uma fonte.",
    "table": "Tabela por uma ou duas dimensões.",
    "graph": "Relações entre duas dimensões (ex.: adjudicante ↔ adjudicatário).",
    "empresa": "Ficha 360: cadastro e CAE, contratos por CPV, clientes, mercado, sócios e gerentes, pessoas, riscos (CIRE e devedores), marcas, firmas e subvenções.",
    "web": "Pesquisa na web os produtos e serviços da empresa; com IA escreve o resumo e lista as fontes.",
}

CHART_KINDS: Tuple[str, ...] = ("bar", "bar-h", "line", "area", "donut", "pie")
CHART_LABELS: Dict[str, str] = {
    "bar": "Barras",
    "bar-h": "Barras horizontais",
    "line": "Linhas",
    "area": "Área",
    "donut": "Circular (donut)",
    "pie": "Circular",
}
WIDTHS: Tuple[int, ...] = (12, 6, 4)

MAX_BLOCKS = 60
MAX_TITLE = 140
MAX_TEXT = 6000
MAX_PROMPT = 2000
MAX_DIMENSIONS = 3
MAX_MEASURES = 6
MAX_KPI = 4
MAX_ROWS = 100
MAX_GRAPH_EDGES = 40
#: Dimensões oferecidas por fonte na interface (as restantes continuam válidas
#: por id, mas não se listam todas para a lista não ficar interminável).
MAX_DIMENSION_OPTIONS = 40
MAX_FEATURES = 30
MAX_REPORTS = 300
MAX_FILE_BYTES = 25 * 1024 * 1024

PDF_KIND = "pdf"

AI_MODES: Tuple[str, ...] = ("sumario", "texto", "insights", "blocos")
AI_MODE_LABELS: Dict[str, str] = {
    "sumario": "Sumário executivo",
    "texto": "Texto de secção",
    "insights": "Destaques dos dados",
    "blocos": "Sugestões de blocos",
}

#: Email de apoio mostrado nos PDF (rodapé e nota final). É editável em
#: *Administração → Relatórios → Definições* (`settings.support_email`); este é
#: o contacto público da plataforma quando nada estiver configurado.
DEFAULT_SUPPORT_EMAIL = store.DEFAULT_SUPPORT_EMAIL

#: Fontes recomendadas (dataset do Visualizador → como aparece no estúdio).
SOURCE_GROUPS: Tuple[Dict[str, str], ...] = (
    {"id": "contratacao", "label": "Contratação Pública", "hint": "Contratos, CPV, regiões, marcas e firmas."},
    {"id": "mercados", "label": "Mercados Financeiros", "hint": "Instrumentos, cotações, notícias e sentimento."},
    {"id": "crm", "label": "CRM", "hint": "Contas, contactos, oportunidades e atividades."},
    {"id": "office", "label": "Plataforma", "hint": "Documentos e dossiês produzidos dentro da plataforma."},
)
RECOMMENDED_SOURCES: Tuple[str, ...] = ("contrato", "cpv", "regiao", "marca", "noticia", "ticker", "cotacao", "topico")

#: Limites das fontes externas (ficha 360 e pesquisa web).
MAX_FICHA_SECOES = 20
MAX_FICHA_ROWS = 12
MAX_WEB_RESULTS = 8
#: Validade da ficha em memória: dentro de um mesmo relatório (ou de duas
#: gerações seguidas) a empresa é recolhida uma só vez, apesar de as variáveis
#: `{{cae}}`/`{{cpv}}` e o próprio bloco a pedirem.
_FICHA_TTL = 600
_ficha_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

#: Cache do catálogo de fontes (o pedido é caro: ontologia + mapping do ES).
_SOURCE_TTL = 60
_source_cache: Dict[str, Tuple[float, Dict[str, Dict[str, Any]]]] = {}


# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "rep") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _text(value: Any, limit: int = 0) -> str:
    result = " ".join(str(value or "").split())
    if limit and len(result) > limit:
        result = result[:limit].rstrip()
    return result


def _long_text(value: Any, limit: int = MAX_TEXT) -> str:
    """Texto multilinha (preserva parágrafos, sem espaços a mais no fim)."""
    result = str(value or "").replace("\r\n", "\n").strip()
    return result[:limit]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    return store.money(value if value is not None else default)


def _as_list(value: Any, limit: int = 0) -> List[str]:
    if isinstance(value, str):
        items: Sequence[Any] = [part for part in re.split(r"[,\n;]+", value)]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    elif value is None:
        items = []
    else:
        items = [value]
    out: List[str] = []
    for item in items:
        ident = _text(item, 80)
        if ident and ident not in out:
            out.append(ident)
    return out[:limit] if limit else out


def slug(value: Any, fallback: str = "relatorio") -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or fallback


def auto_key(report_id: str) -> str:
    """Chave com que um relatório é entregue automaticamente (`estudio:<id>`)."""
    return f"estudio:{_text(report_id, 60)}"


def report_id_from_auto(key: Any) -> Optional[str]:
    """Id do relatório a partir da chave de entrega automática (ou `None`)."""
    text = _text(key, 80)
    if not text.lower().startswith("estudio:"):
        return None
    return text.split(":", 1)[1].strip() or None


def is_auto_key(key: Any) -> bool:
    return report_id_from_auto(key) is not None


# --------------------------------------------------------------------------
# Parâmetros do relatório (variáveis)
# --------------------------------------------------------------------------
# Um modelo que vale para muitas empresas (concorrência, área de CAE) não pode
# ter o NIF escrito à mão em cada bloco: guarda **variáveis** no relatório e os
# blocos referem-nas como `{{empresa}}`. Quem produz o relatório muda a empresa
# num sítio só.
VAR_IDS: Tuple[str, ...] = ("empresa", "nome", "nif", "cae", "cpv", "site")
#: Variáveis que o estúdio calcula a partir da empresa (não se pedem ao autor).
VAR_DERIVED: Tuple[str, ...] = ("nif", "nome", "cae", "cpv", "site")
MAX_VAR_VALUE = 160

_VAR_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}", re.IGNORECASE)


def vars_spec(template_id: str = "") -> List[Dict[str, str]]:
    """Campos de parâmetros que este modelo pede (vazio nos modelos gerais)."""
    model = TEMPLATES_BY_ID.get(_text(template_id, 60).lower())
    return [dict(item) for item in (model or {}).get("vars") or []]


def normalise_vars(value: Any, template_id: str = "") -> Dict[str, str]:
    """Guarda só as variáveis conhecidas, com o tamanho limitado."""
    raw = value if isinstance(value, dict) else {}
    allowed = {str(item.get("id")) for item in vars_spec(template_id)} | set(VAR_IDS)
    out: Dict[str, str] = {}
    for key, item in raw.items():
        ident = _text(key, 40).lower()
        if ident not in allowed:
            continue
        text = _text(item, MAX_VAR_VALUE)
        if text:
            out[ident] = text
    return out


def has_tokens(value: Any) -> bool:
    """Há alguma variável por substituir neste valor?"""
    if isinstance(value, str):
        return bool(_VAR_TOKEN.search(value))
    if isinstance(value, dict):
        return any(has_tokens(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_tokens(item) for item in value)
    return False


def substitute(value: Any, mapping: Dict[str, str]) -> Any:
    """Troca `{{var}}` pelo valor. Sem valor, o token desaparece (não fica cru)."""
    if isinstance(value, str):
        texto = _VAR_TOKEN.sub(lambda match: str(mapping.get(match.group(1).lower(), "")), value)
        # Um token sem valor deixava um espaço duplo no meio da frase.
        return re.sub(r"[ \t]{2,}", " ", texto).strip()
    if isinstance(value, dict):
        return {key: substitute(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, mapping) for item in value]
    return value


def apply_vars(block: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """Cópia do bloco com as variáveis resolvidas (título, filtros, pesquisa…)."""
    if not mapping or not has_tokens(block):
        return block
    resolved = copy.deepcopy(block)
    for key in ("title", "subtitle", "description", "text", "prompt", "search", "empresa", "query", "site", "format", "chart"):
        if key in resolved:
            resolved[key] = substitute(resolved[key], mapping)
    resolved["filters"] = substitute(resolved.get("filters") or {}, mapping)
    return resolved


# --------------------------------------------------------------------------
# Acessos (administradores, gestores de plataforma e gestores de relatórios)
# --------------------------------------------------------------------------
def can_studio(email: Any, role: str = "member") -> bool:
    """Quem pode criar relatórios: `admin`, `manager` ou conta da lista.

    A lista (`settings.report_managers`) existe para dar acesso a contas sem
    papel de gestão — por exemplo a quem produz os relatórios na equipa.
    """
    return store.is_report_manager(email, role)


def support_email() -> str:
    """Email de apoio que vai nos PDF (configurável na administração)."""
    configured = str(store.settings().get("support_email") or "").strip()
    return configured or DEFAULT_SUPPORT_EMAIL


# --------------------------------------------------------------------------
# Fontes (catálogo do Visualizador)
# --------------------------------------------------------------------------
def _viz():
    """Import tardio do serviço do Visualizador (é ele que conhece as fontes)."""
    from api import visualizador_service as service  # noqa: PLC0415

    return service


def _source_entry(dataset: Dict[str, Any]) -> Dict[str, Any]:
    dimensions = [
        {
            "id": entry.get("id"),
            "label": entry.get("label") or entry.get("id"),
            "type": entry.get("type"),
            "unit": entry.get("unit"),
        }
        for entry in (dataset.get("dimensions") or [])
        if entry.get("id") and entry.get("groupable", True)
    ]
    measures = [
        {
            "id": measure.get("id"),
            "label": measure.get("label") or measure.get("id"),
            "kind": measure.get("kind"),
            "format": measure.get("format") or "number",
            "unit": measure.get("unit"),
        }
        for measure in (dataset.get("measures") or [])
        if measure.get("id")
    ]
    defaults = dataset.get("defaults") or {}
    return {
        "id": dataset.get("id"),
        "label": dataset.get("label") or dataset.get("id"),
        "description": dataset.get("description") or "",
        "domain": dataset.get("domain") or "local",
        "icon": dataset.get("icon") or "database",
        "kind": dataset.get("kind"),
        "recommended": dataset.get("id") in RECOMMENDED_SOURCES,
        "dimensions": dimensions[:MAX_DIMENSION_OPTIONS],
        "measures": measures,
        "defaults": defaults,
        "suggestions": [
            {
                "chart": item.get("chart"),
                "title": item.get("title") or "",
                "dimensions": item.get("dimensions") or [],
                "measures": item.get("measures") or [],
            }
            for item in (dataset.get("suggestions") or [])
        ][:6],
    }


def sources(scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fontes disponíveis para os relatórios, com dimensões e medidas."""
    problems: List[str] = []
    entries: List[Dict[str, Any]] = []
    try:
        # O catálogo dá a *disponibilidade* de cada dataset (o âmbito do
        # Visualizador decide se os privados entram); as definições completas vêm
        # de uma só passagem sobre os datasets.
        catalog = _viz().catalog(scope)
        allowed = {
            str(item.get("id") or "")
            for item in catalog.get("datasets") or []
            if item.get("aggregation") and item.get("available", True)
        }
        for dataset in _viz()._all_datasets():  # noqa: SLF001 - mesma fonte do Visualizador
            if str(dataset.get("id") or "") not in allowed:
                continue
            entry = _source_entry(dataset)
            if entry["dimensions"] or entry["measures"]:
                entries.append(entry)
    except Exception as exc:  # noqa: BLE001 - sem ES/ontologia o estúdio continua a servir texto
        logger.warning("Estúdio: catálogo de fontes indisponível (%s)", exc)
        problems.append(f"Catálogo de fontes indisponível: {exc}")

    groups = []
    for group in SOURCE_GROUPS:
        members = [entry["id"] for entry in entries if entry["domain"] == group["id"]]
        if members:
            groups.append({**group, "sources": members})
    known = {member for group in groups for member in group["sources"]}
    rest = [entry["id"] for entry in entries if entry["id"] not in known]
    if rest:
        groups.append({"id": "outras", "label": "Outras fontes", "hint": "Restantes datasets da plataforma.", "sources": rest})

    entries.sort(key=lambda entry: (not entry["recommended"], entry["label"]))
    return {
        "sources": entries,
        "groups": groups,
        "block_types": [{"id": key, "label": BLOCK_LABELS[key], "hint": BLOCK_HINTS[key]} for key in BLOCK_TYPES],
        "chart_types": [{"id": key, "label": CHART_LABELS[key]} for key in CHART_KINDS],
        "ai_modes": [{"id": key, "label": AI_MODE_LABELS[key]} for key in AI_MODES],
        "limits": {
            "max_blocks": MAX_BLOCKS,
            "max_dimensions": MAX_DIMENSIONS,
            "max_measures": MAX_MEASURES,
            "max_kpi": MAX_KPI,
            "max_rows": MAX_ROWS,
            "max_graph_edges": MAX_GRAPH_EDGES,
            "max_text": MAX_TEXT,
            "widths": list(WIDTHS),
        },
        "problems": problems,
        "available": bool(entries),
        "generated_at": _now(),
    }


def _source_map(scope: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Mapa id → fonte. Fica em cache 60 s: um relatório com 20 blocos pede-o 20 vezes."""
    key = "all" if (scope or {}).get("see_all") else "own"
    now = time.time()
    cached = _source_cache.get(key)
    if cached and now - float(cached[0]) < _SOURCE_TTL:
        return cached[1]
    listing = sources(scope)
    mapping = {str(entry["id"]): entry for entry in listing["sources"]}
    _source_cache[key] = (now, mapping)
    return mapping


# --------------------------------------------------------------------------
# Ficha 360 da empresa (bloco `empresa`)
# --------------------------------------------------------------------------
# O Visualizador agrega contratos; a **ficha** junta o que não se agrega: quem é
# a empresa (cadastro e CAE), quem a gere (órgãos sociais e pessoas), em que
# processos entra (CIRE e devedores), que marcas e firmas tem e como se posiciona
# no mercado. Vem do serviço de descoberta (`recolher`) — o mesmo que alimenta o
# painel de empresa —, para não haver uma segunda recolha de dados.
COLUNA = Tuple[str, Tuple[str, ...], str]  # (etiqueta, chaves possíveis, formato)


def _digitos(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _valor(item: Any, chaves: Sequence[str]) -> Any:
    """Primeiro campo preenchido entre as variantes de nome das fontes."""
    if not isinstance(item, dict):
        return None
    for chave in chaves:
        if item.get(chave) not in (None, "", [], {}):
            return item[chave]
    return None


def _celula(value: Any, formato: str = "text") -> str:
    if value in (None, "", [], {}):
        return "—"
    if isinstance(value, (list, tuple)):
        return _text(" · ".join(_text(item, 50) for item in list(value)[:3]), 80)
    if isinstance(value, dict):
        return _text(" · ".join(f"{chave}: {_text(item, 40)}" for chave, item in list(value.items())[:2]), 80)
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if isinstance(value, (int, float)):
        return format_value(value, formato if formato in {"money", "number", "percent"} else "number")
    return _text(value, 90)


def _tabela(items: Any, colunas: Sequence[COLUNA], limit: int = MAX_FICHA_ROWS) -> Tuple[List[str], List[List[str]]]:
    """Tabela a partir de registos de forma variável (o que não existe fica —)."""
    linhas: List[List[str]] = []
    for item in items if isinstance(items, (list, tuple)) else []:
        if isinstance(item, dict):
            linha = [_celula(_valor(item, chaves), formato) for _label, chaves, formato in colunas]
        else:
            linha = [_celula(item)] + ["—"] * (len(colunas) - 1)
        if all(celula == "—" for celula in linha):
            continue
        linhas.append(linha)
        if len(linhas) >= limit:
            break
    return [label for label, _chaves, _formato in colunas], linhas


def _pessoa_linhas(pessoas: Any, colunas: Sequence[COLUNA], limit: int = MAX_FICHA_ROWS) -> Tuple[List[str], List[List[str]]]:
    """Pessoas com os cargos: uma linha por pessoa (o cargo pode ser uma lista)."""
    linhas: List[List[str]] = []
    for pessoa in pessoas if isinstance(pessoas, (list, tuple)) else []:
        if not isinstance(pessoa, dict):
            continue
        cargos = pessoa.get("latest_roles") or pessoa.get("roles") or pessoa.get("cargos") or []
        cargo = cargos[0] if isinstance(cargos, (list, tuple)) and cargos else {}
        if not isinstance(cargo, dict):
            cargo = {}
        registo = {
            "nome": _valor(pessoa, ("name", "nome")),
            "cargo": _valor(cargo, ("role", "cargo", "funcao")) or _valor(pessoa, ("role", "cargo")),
            "orgao": _valor(cargo, ("role_org", "orgao", "orgao_social")) or _valor(pessoa, ("role_org", "orgao")),
            "empresa": _valor(cargo, ("company_name", "empresa")) or _valor(pessoa, ("company_name", "empresa")),
            "data": _valor(cargo, ("date", "publication_date", "data")) or _valor(pessoa, ("last_seen", "data")),
            "quota": _valor(cargo, ("quota",)),
            "nif": _valor(pessoa, ("nif",)),
            "tipo": _valor(pessoa, ("is_company",)),
        }
        linha = [_celula(_valor(registo, chaves), formato) for _label, chaves, formato in colunas]
        if all(celula == "—" for celula in linha):
            continue
        linhas.append(linha)
        if len(linhas) >= limit:
            break
    return [label for label, _chaves, _formato in colunas], linhas


def empresa_nif(value: Any) -> str:
    """NIF de 9 dígitos a partir de um NIF ou do nome de uma empresa."""
    texto = _text(value, 160)
    if not texto or "{{" in texto:
        # Um token por resolver (`{{empresa}}`) nunca é um nome de empresa: sem
        # esta guarda, o resolver fuzzy devolvia outra empresa qualquer.
        return ""
    digitos = _digitos(texto)
    if len(digitos) == 9 and digitos == texto.replace(" ", ""):
        return digitos
    from api import descoberta_service as descoberta  # noqa: PLC0415

    try:
        resolvido = descoberta.resolver(texto, size=5)
    except Exception as exc:  # noqa: BLE001 - a resolução depende do Elasticsearch
        logger.warning("Estúdio: NIF de «%s» não resolvido (%s)", texto, exc)
        return ""
    for item in resolvido.get("items") or []:
        nif = _digitos((item or {}).get("nif"))
        if len(nif) == 9:
            return nif
    return ""


def _ficha_recolha(nif: str) -> Dict[str, Any]:
    """Recolha da descoberta, em cache: as variáveis e o bloco pedem a mesma."""
    agora = time.time()
    guardado = _ficha_cache.get(nif)
    if guardado and agora - guardado[0] < _FICHA_TTL:
        return copy.deepcopy(guardado[1])
    from api import descoberta_service as descoberta  # noqa: PLC0415

    recolha = descoberta.recolher(nif)
    _ficha_cache[nif] = (agora, copy.deepcopy(recolha))
    return recolha


def _agregados_dos_contratos(nif: str, scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Agregados por CPV, ano e adjudicante (Visualizador; amostra se falhar)."""
    out: Dict[str, Any] = {"fonte": "", "cpv": [], "ano": [], "adjudicantes": []}
    filtros = {"adjudicatario_nif": [nif]}
    consultas = {
        "cpv": (["cpv_codigo"], ["contagem", "soma_preco"], 12),
        "ano": (["ano"], ["contagem", "soma_preco"], 24),
        "adjudicantes": (["adjudicante"], ["contagem", "soma_preco"], 10),
    }
    try:
        service = _viz()
    except Exception:  # noqa: BLE001
        return out
    for chave, (dimensoes, medidas, limite) in consultas.items():
        try:
            resultado = service.run_query(
                {
                    "dataset": "contrato",
                    "dimensions": dimensoes,
                    "measures": medidas,
                    "filters": dict(filtros),
                    "limit": limite,
                    "top_n": limite,
                },
                scope=scope,
            )
        except Exception as exc:  # noqa: BLE001 - a ficha continua com a amostra
            logger.debug("Estúdio: agregado %s de %s falhou (%s)", chave, nif, exc)
            continue
        if resultado.get("error"):
            continue
        out[chave] = resultado.get("rows") or []
    if out["cpv"] or out["ano"]:
        out["fonte"] = "index"
    return out


def _ficha_contratos_sections(
    secoes: Dict[str, Any],
    agregados: Dict[str, Any],
    *,
    ano_key: str = "ano",
    medida: str = "soma_preco",
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    cpv_rows = agregados.get("cpv") or []
    if cpv_rows:
        sections.append(
            {
                "kind": "table",
                "title": "Contratos por CPV",
                "columns": ["CPV", "Contratos", "Valor"],
                "rows": [
                    [
                        _text(row.get("cpv_codigo") or "—", 40),
                        _celula(row.get("contagem"), "number"),
                        _celula(row.get(medida), "money"),
                    ]
                    for row in cpv_rows[:12]
                ],
            }
        )
    ano_rows = [row for row in (agregados.get("ano") or []) if _digitos(row.get(ano_key))]
    if ano_rows:
        sections.append(
            {
                "kind": "chart",
                "title": "Valor contratado por ano",
                "chart": "bar",
                "dimension": ano_key,
                "measure": medida,
                "format": "money",
                "rows": sorted(ano_rows, key=lambda row: str(row.get(ano_key)))[-14:],
            }
        )
    adjudicantes = agregados.get("adjudicantes") or []
    if adjudicantes:
        sections.append(
            {
                "kind": "table",
                "title": "Maiores clientes (adjudicantes)",
                "columns": ["Adjudicante", "Contratos", "Valor"],
                "rows": [
                    [
                        _text(row.get("adjudicante") or "—", 60),
                        _celula(row.get("contagem"), "number"),
                        _celula(row.get(medida), "money"),
                    ]
                    for row in adjudicantes[:10]
                ],
            }
        )
    contratos = secoes.get("contratos") or {}
    if not cpv_rows and contratos.get("contratos"):
        # Sem agregação do índice (ES em baixo, por exemplo): usa-se a amostra
        # do dossiê, dizendo que é amostra.
        por_cpv: Dict[str, List[float]] = {}
        for contrato in contratos["contratos"]:
            chave = f"{_text(contrato.get('cpv') or '—', 20)} — {_text(contrato.get('cpv_desc') or '', 40)}".strip(" —")
            entrada = por_cpv.setdefault(chave, [0.0, 0.0])
            entrada[0] += 1
            entrada[1] += float(contrato.get("valor") or 0.0)
        sections.append(
            {
                "kind": "table",
                "title": f"Contratos por CPV (amostra de {len(contratos['contratos'])})",
                "columns": ["CPV", "Contratos", "Valor"],
                "rows": [
                    [_text(chave, 70), _celula(valores[0], "number"), _celula(valores[1], "money")]
                    for chave, valores in sorted(por_cpv.items(), key=lambda item: item[1][1], reverse=True)[:12]
                ],
            }
        )
    return sections


def _ficha_registos_sections(secoes: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    cire = secoes.get("cire") or {}
    insolvencias = cire.get("insolvencias") or []
    if insolvencias:
        colunas, linhas = _tabela(
            insolvencias,
            (
                ("Data", ("data", "data_publicacao", "publication_date"), "text"),
                ("Espécie", ("especie", "ato", "event"), "text"),
                ("Tribunal", ("tribunal",), "text"),
                ("Processo", ("processo", "processo_numero"), "text"),
            ),
        )
        sections.append({"kind": "table", "title": "Insolvências (CIRE)", "columns": colunas, "rows": linhas})
    # A mesma fronteira que a ficha de empresa usa: uma menção num processo de
    # terceiros (credor) **não** é uma insolvência da empresa.
    if cire:
        total_insolvencias = int(cire.get("insolvencias_total") or len(insolvencias))
        mencoes = int(cire.get("mencoes_total") or 0)
        if cire.get("papel_insolvente"):
            nota = f"Processos em que a empresa é insolvente: {total_insolvencias}."
        elif mencoes:
            nota = f"A empresa não é insolvente: aparece em {mencoes} processo(s) do CIRE como credora ou interveniente."
        elif insolvencias or "insolvencias_total" in cire:
            nota = "Sem insolvências nem processos registados no CIRE para esta empresa."
        else:
            nota = ""
        if nota:
            sections.append({"kind": "text", "title": "Processos no CIRE", "text": nota})
    intervenientes = cire.get("intervenientes") or []
    if intervenientes:
        colunas, linhas = _tabela(
            intervenientes,
            (
                ("Processo", ("processo", "processo_numero"), "text"),
                ("Nome", ("nome", "insolvente"), "text"),
                ("Papel", ("papel", "role"), "text"),
                ("NIF", ("nif",), "text"),
            ),
            limit=10,
        )
        sections.append({"kind": "table", "title": "Intervenientes em processos (CIRE)", "columns": colunas, "rows": linhas})

    devedores = secoes.get("devedores") or {}
    if devedores.get("devedor") or devedores.get("items"):
        itens = devedores.get("items") or devedores.get("entidades") or []
        colunas, linhas = _tabela(
            itens,
            (
                ("Entidade", ("entidade", "entidade_nome", "nome", "fonte"), "text"),
                ("Escalão", ("escalao", "escaloes"), "text"),
                ("Valor mínimo", ("valor_min", "maior_valor_min", "valor"), "money"),
                ("Período", ("periodo", "ano", "data"), "text"),
            ),
        )
        texto = "A empresa consta das listas públicas de devedores."
        if isinstance(devedores.get("escaloes"), (list, tuple)) and devedores["escaloes"]:
            texto = f"Escalões em que consta: {_text(' · '.join(_text(x, 30) for x in devedores['escaloes'][:4]), 120)}."
        sections.append({"kind": "text", "title": "Devedores (Finanças e Segurança Social)", "text": texto})
        if linhas:
            sections.append({"kind": "table", "title": "Registos de dívida", "columns": colunas, "rows": linhas})

    marcas = secoes.get("marcas") or {}
    if marcas.get("items"):
        colunas, linhas = _tabela(
            marcas["items"],
            (
                ("Marca", ("mark_name", "nome", "marca"), "text"),
                ("Tipo", ("mark_type", "tipo", "modalidade"), "text"),
                ("Pedido", ("application_date", "data_pedido", "data"), "text"),
                ("Fase", ("current_phase", "fase", "situacao"), "text"),
            ),
            limit=8,
        )
        sections.append({"kind": "table", "title": f"Marcas (INPI) — {int(marcas.get('total') or len(linhas))}", "columns": colunas, "rows": linhas})

    firmas = secoes.get("firmas") or {}
    if firmas.get("items"):
        colunas, linhas = _tabela(
            firmas["items"],
            (
                ("Firma", ("nome", "firma", "name"), "text"),
                ("CAE", ("cae",), "text"),
                ("Concelho", ("concelho",), "text"),
                ("Situação", ("situacao",), "text"),
                ("Score", ("score",), "number"),
            ),
            limit=8,
        )
        sections.append({"kind": "table", "title": f"Firmas e CAE (RNPC) — {int(firmas.get('total') or len(linhas))}", "columns": colunas, "rows": linhas})

    subvencoes = secoes.get("subvencoes") or {}
    itens = subvencoes.get("items") or []
    if itens:
        colunas, linhas = _tabela(
            itens,
            (
                ("Entidade", ("entidade", "entidade_nome", "nome", "fonte"), "text"),
                ("Ano", ("ano", "year", "data"), "text"),
                ("Valor", ("valor", "montante", "importe"), "money"),
                ("Programa", ("programa", "medida", "tipo"), "text"),
            ),
            limit=8,
        )
        sections.append(
            {
                "kind": "table",
                "title": f"Subvenções públicas — {format_value(subvencoes.get('valor_total') or subvencoes.get('montante'), 'money')}",
                "columns": colunas,
                "rows": linhas,
            }
        )

    noticias = secoes.get("noticias") or {}
    if noticias.get("items"):
        itens_noticia = [
            f"{_text(_valor(item, ('title', 'titulo')) or '—', 90)} — {_text(_valor(item, ('publisher', 'fonte', 'source')) or '', 40)}"
            f" ({_text(_valor(item, ('published', 'data', 'published_at')) or '', 20)})"
            for item in noticias["items"][:6]
        ]
        sections.append({"kind": "list", "title": "Imprensa", "items": itens_noticia})
    return sections


def _ficha_pessoas_sections(secoes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sócios, gerentes e restantes pessoas com cargos registados."""
    colunas: Tuple[COLUNA, ...] = (
        ("Nome", ("nome",), "text"),
        ("Cargo", ("cargo",), "text"),
        ("Órgão", ("orgao",), "text"),
        ("Quota", ("quota",), "text"),
        ("Desde", ("data",), "text"),
    )
    pessoas: List[Dict[str, Any]] = []
    rede = secoes.get("rede") or {}
    pessoas.extend(rede.get("cargos_sociais") or [])
    fonte_pessoas = secoes.get("pessoas") or {}
    if isinstance(fonte_pessoas.get("pessoas"), (list, tuple)):
        pessoas.extend(item for item in fonte_pessoas["pessoas"] if isinstance(item, dict))
    if isinstance(fonte_pessoas.get("societario"), (list, tuple)):
        for item in fonte_pessoas["societario"]:
            if isinstance(item, dict):
                pessoas.append(
                    {
                        "name": _valor(item, ("nome", "name")),
                        "nif": _valor(item, ("nif",)),
                        "latest_roles": [
                            {
                                "role": _valor(item, ("cargo", "role")),
                                "role_org": _valor(item, ("orgao", "role_org")),
                                "date": _valor(item, ("data", "date")),
                                "quota": _valor(item, ("quota",)),
                            }
                        ],
                    }
                )
    vistos: set = set()
    unicas: List[Dict[str, Any]] = []
    for pessoa in pessoas:
        chave = _digitos(pessoa.get("nif")) or _text(pessoa.get("name") or pessoa.get("nome"), 80).lower()
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        unicas.append(pessoa)

    sections: List[Dict[str, Any]] = []
    if unicas:
        etiquetas, linhas = _pessoa_linhas(unicas, colunas)
        sections.append({"kind": "table", "title": f"Sócios, gerentes e pessoas — {len(unicas)}", "columns": etiquetas, "rows": linhas})

    societario = secoes.get("societario") or {}
    if societario.get("items"):
        etiquetas, linhas = _tabela(
            societario["items"],
            (
                ("Data", ("data", "data_publicacao", "publication_date"), "text"),
                ("Ato", ("acto", "tipo", "descricao", "objeto", "sumario"), "text"),
                ("Publicação", ("publicacao", "publicacao_id", "id"), "text"),
            ),
            limit=10,
        )
        titulo = f"Atos societários (registo comercial) — {int(societario.get('total') or len(linhas))}"
        sections.append({"kind": "table", "title": titulo, "columns": etiquetas, "rows": linhas})
    return sections


def _ficha_mercado_sections(secoes: Dict[str, Any]) -> List[Dict[str, Any]]:
    mercado = secoes.get("mercado") or {}
    if not mercado:
        return []
    sections: List[Dict[str, Any]] = []
    cae = mercado.get("cae") or {}
    compatibilidade = mercado.get("compatibilidade") or {}
    dependencia = mercado.get("dependencia") or {}
    evolucao = mercado.get("evolucao") or {}
    frases: List[str] = []
    if cae.get("cae_principal_label") or cae.get("cae_principal"):
        frases.append(f"CAE principal {cae.get('cae_principal') or '—'} — {cae.get('cae_principal_label') or 'sem descrição'}.")
    if compatibilidade.get("grau") and compatibilidade.get("grau") != "desconhecida":
        frases.append(f"Compatibilidade CAE/contratos: {compatibilidade.get('grau')} (score {compatibilidade.get('score')}).")
    if dependencia.get("n_entidades"):
        frases.append(
            f"{int(dependencia.get('n_entidades') or 0)} entidades compradoras; maior quota "
            f"{round(float(dependencia.get('maior_quota') or 0.0) * 100, 1)} %; HHI {round(float(dependencia.get('hhi') or 0.0), 3)}."
        )
    if evolucao.get("anos"):
        variacao = evolucao.get("variacao")
        variacao_texto = f"{round(float(variacao) * 100, 1)} %" if isinstance(variacao, (int, float)) else "n/d"
        frases.append(
            f"Evolução {evolucao['anos'][0]}–{evolucao['anos'][-1]}: variação {variacao_texto}"
            + (f", CAGR {round(float(evolucao['cagr']) * 100, 1)} %" if isinstance(evolucao.get("cagr"), (int, float)) else "")
            + "."
        )
    if mercado.get("taxa_sem_concurso") is not None:
        frases.append(f"Contratos sem concurso: {round(float(mercado.get('taxa_sem_concurso') or 0.0) * 100, 1)} %.")
    if mercado.get("perfil"):
        frases.append(_text(mercado["perfil"], 240))
    alertas = [
        f"{_text(item.get('detalhe') or item.get('tipo'), 200)}" + (f" ({item['severidade']})" if item.get("severidade") else "")
        for item in (mercado.get("alertas") or [])
        if isinstance(item, dict)
    ] or [str(item) for item in (mercado.get("alertas") or []) if not isinstance(item, dict)]
    if frases:
        sections.append({"kind": "text", "title": "Mercado e posicionamento", "text": " ".join(frases)})
    if alertas:
        sections.append({"kind": "list", "title": "Alertas de mercado", "items": alertas[:6]})
    entidades = mercado.get("entidades") or []
    if entidades:
        etiquetas, linhas = _tabela(
            entidades,
            (
                ("Entidade", ("nome", "name"), "text"),
                ("Contratos", ("contratos",), "number"),
                ("Valor", ("valor",), "money"),
                ("Quota", ("quota",), "number"),
            ),
            limit=10,
        )
        sections.append({"kind": "table", "title": "Quem compra à empresa", "columns": etiquetas, "rows": linhas})
    cpvs = mercado.get("cpvs") or []
    if cpvs and (_valor(cpvs[0], ("classe", "cpv", "codigo")) if isinstance(cpvs[0], dict) else None):
        etiquetas, linhas = _tabela(
            cpvs,
            (
                ("CPV", ("cpv", "codigo", "classe"), "text"),
                ("Divisão", ("divisao",), "text"),
                ("Contratos", ("contratos", "contagem"), "number"),
                ("Valor", ("valor",), "money"),
                ("Quota", ("quota",), "number"),
            ),
            limit=10,
        )
        sections.append({"kind": "table", "title": "Famílias de CPV da empresa", "columns": etiquetas, "rows": linhas})
    return sections


def empresa_ficha(value: Any, scope: Optional[Dict[str, Any]] = None, *, nome: str = "") -> Dict[str, Any]:
    """Ficha 360 de uma empresa (por NIF ou nome), normalizada em secções.

    Devolve `kpis` e `sections` com formas genéricas (texto, tabela, lista,
    gráfico) para o PDF e a pré-visualização desenharem sem código próprio.
    """
    ficha: Dict[str, Any] = {
        "empresa": _text(value, 160),
        "nif": "",
        "nome": _text(nome, 160),
        "encontrada": False,
        "site": "",
        "cae": "",
        "cae_label": "",
        "kpis": [],
        "sections": [],
        "fontes": [],
        "avisos": [],
        "error": None,
    }
    nif = empresa_nif(value)
    ficha["nif"] = nif
    if not nif:
        ficha["error"] = (
            f"Não foi possível identificar a empresa «{_text(value, 80) or '(vazio)'}»: indique o NIF (9 dígitos) "
            "ou um nome que exista na plataforma."
        )
        return ficha

    try:
        recolha = _ficha_recolha(nif)
    except Exception as exc:  # noqa: BLE001 - a ficha é uma fonte externa
        logger.warning("Estúdio: ficha de %s falhou (%s)", nif, exc)
        ficha["error"] = f"Ficha indisponível: {exc}"
        return ficha

    secoes = recolha.get("secoes") or {}
    kpis = recolha.get("kpis") or {}
    cadastro = (secoes.get("cadastro") or {}).get("cadastro") or {}
    perfil = (secoes.get("cadastro") or {}).get("perfil") or {}
    mercado = secoes.get("mercado") or {}
    cae = mercado.get("cae") or {}
    ficha.update(
        {
            "nome": _text(cadastro.get("name") or cadastro.get("nome") or recolha.get("nome") or ficha["nome"], 160),
            "encontrada": bool(recolha.get("encontrada")),
            "site": _text(perfil.get("site"), 160),
            "cae": _text(cae.get("cae_principal") or cadastro.get("cae_principal"), 20),
            "cae_label": _text(cae.get("cae_principal_label"), 120),
            "fontes": [
                {"id": item.get("id"), "label": item.get("label"), "estado": item.get("estado"), "total": item.get("total")}
                for item in recolha.get("fontes") or []
            ],
            "avisos": [str(item) for item in recolha.get("avisos") or []],
        }
    )

    # ------------------------------------------------------------ identificação
    papeis = []
    if cadastro.get("adjudicatario"):
        papeis.append("adjudicatária")
    if cadastro.get("adjudicante"):
        papeis.append("adjudicante")
    contratos = (secoes.get("contratos") or {}).get("resumo") or {}
    anos = []
    for item in (secoes.get("contratos") or {}).get("contratos") or []:
        if item.get("ano"):
            anos.append(int(item["ano"]))
    identificacao = [
        f"Empresa: {ficha['nome'] or '—'} (NIF {nif})",
        f"Atividade (CAE): {ficha['cae'] or '—'} — {ficha['cae_label'] or 'sem descrição no registo'}",
        f"Contratos no Portal BASE: {int(kpis.get('contratos') or 0)}"
        + (f" · valor total {format_value(kpis.get('valor_total'), 'money')}" if kpis.get("valor_total") else ""),
    ]
    if anos:
        identificacao.append(f"Período analisado (amostra de contratos): {min(anos)}–{max(anos)}")
    if papeis:
        identificacao.append(f"Papel na contratação pública: {', '.join(papeis)}")
    if ficha["site"]:
        identificacao.append(f"Site oficial: {ficha['site']}")
    if contratos.get("adjudicantes_distintos"):
        identificacao.append(f"Adjudicantes distintos: {int(contratos['adjudicantes_distintos'])}")
    ficha["sections"].append({"kind": "text", "title": "Identificação", "text": " · ".join(identificacao)})

    sinais = [
        f"{_text(item.get('detalhe') or item.get('padrao'), 160)}"
        for item in (kpis.get("sinais") or [])
        if isinstance(item, dict)
    ]
    risco = (secoes.get("risco") or {}).get("risco") or {}
    if risco.get("nivel_label"):
        sinais.append(f"Risco de contratação: {risco.get('nivel_label')} (score {risco.get('score')}, cobertura {risco.get('cobertura')}).")
    for aviso in risco.get("avisos") or []:
        sinais.append(_text(aviso, 200))
    if sinais:
        ficha["sections"].append({"kind": "list", "title": "Sinais e alertas", "items": sinais[:8]})

    # --------------------------------------------------------------- indicadores
    indicadores = [
        ("Contratos", kpis.get("contratos"), "number"),
        ("Valor contratado", kpis.get("valor_total"), "money"),
        ("Valor mediano", kpis.get("valor_mediano"), "money"),
        ("Adjudicantes", kpis.get("adjudicantes"), "number"),
        ("Concentração no maior cliente", kpis.get("concentracao_maior"), "percent"),
        ("Insolvências (CIRE)", kpis.get("insolvencias"), "number"),
        ("Pessoas com cargos", kpis.get("pessoas"), "number"),
        ("Marcas", kpis.get("marcas"), "number"),
        ("Firmas", kpis.get("firmas"), "number"),
        ("Subvenções", kpis.get("subvencoes_valor"), "money"),
    ]
    ficha["kpis"] = [
        {"label": label, "value": format_value(valor, formato)}
        for label, valor, formato in indicadores
        if valor not in (None, "", 0, 0.0)
    ]

    # ------------------------------------------------------------------ contratos
    agregados = _agregados_dos_contratos(nif, scope)
    ficha["contratos"] = agregados.get("fonte") or "amostra"
    ficha["cpvs"] = [str(row.get("cpv_codigo")).strip() for row in agregados.get("cpv") or [] if _digitos(row.get("cpv_codigo"))]
    ficha["sections"].extend(_ficha_contratos_sections(secoes, agregados))
    ficha["sections"].extend(_ficha_mercado_sections(secoes))
    ficha["sections"].extend(_ficha_pessoas_sections(secoes))
    ficha["sections"].extend(_ficha_registos_sections(secoes))

    # -------------------------------------------------------------------- fontes
    com_dados = [item for item in ficha["fontes"] if item.get("estado") == "ok"]
    sem_dados = [item.get("label") or item.get("id") for item in ficha["fontes"] if item.get("estado") != "ok"]
    resumo = f"{len(com_dados)} de {len(ficha['fontes'])} fontes com dados"
    if sem_dados:
        resumo += f"; sem dados: {_text(', '.join(str(item) for item in sem_dados[:10]), 200)}"
    ficha["sections"].append({"kind": "note", "title": "Fontes da ficha", "text": resumo + "."})
    # A nota das fontes fica sempre: diz o que não respondeu. O corte é só uma
    # válvula de segurança para uma ficha com tudo preenchido.
    nota_fontes = ficha["sections"][-1]
    ficha["sections"] = [section for section in ficha["sections"][:-1] if section.get("title")][:MAX_FICHA_SECOES]
    ficha["sections"].append(nota_fontes)
    return ficha


# --------------------------------------------------------------------------
# Produtos e serviços pela web (bloco `web`)
# --------------------------------------------------------------------------
_WEB_SISTEMA = (
    "És analista de inteligência de mercado da plataforma IQ OS. Escreves em português de Portugal, "
    "só com base nos excertos fornecidos: não inventes produtos, serviços, preços, certificações nem clientes."
)


def _dominio(url: Any) -> str:
    texto = _text(url, 200)
    texto = re.sub(r"^https?://", "", texto)
    return texto.split("/", 1)[0].lower()


def web_products(query: Any, *, limit: int = 5, site: Any = "", usar_ia: bool = True) -> Dict[str, Any]:
    """Pesquisa na web os produtos e serviços descritos para uma consulta.

    Devolve o texto da IA (quando há modelo) e, sempre, os excertos e as fontes
    — sem modelo o relatório continua a ter material factual e verificável.
    """
    texto_pesquisa = _text(query, 300)
    if "{{" in texto_pesquisa:
        # Sem valor para a variável, não se pesquisa por `{{nome}}` à letra.
        texto_pesquisa = _text(substitute(texto_pesquisa, {}), 300)
    resultado: Dict[str, Any] = {
        "query": texto_pesquisa,
        "site": _text(site, 160),
        "engine": "",
        "results": [],
        "text": "",
        "ai": False,
        "notes": [],
        "sections": [],
        "error": None,
    }
    if not texto_pesquisa:
        resultado["error"] = "Indique o que pesquisar (ex.: «{{nome}} produtos e serviços»)."
        return resultado
    try:
        from api import tools  # noqa: PLC0415

        itens = tools.web_search(texto_pesquisa, max_results=max(1, min(limit, MAX_WEB_RESULTS)))
    except Exception as exc:  # noqa: BLE001 - a web é uma ajuda, não um requisito
        logger.warning("Estúdio: pesquisa web de %r falhou (%s)", texto_pesquisa, exc)
        resultado["error"] = f"Pesquisa web indisponível: {exc}"
        return resultado
    limpos = [
        {
            "title": _text(item.get("title"), 200),
            "href": _text(item.get("href") or item.get("url"), 300),
            "body": _text(item.get("body") or item.get("snippet"), 400),
            "source": _text(item.get("source") or item.get("engine"), 40),
        }
        for item in itens or []
        if isinstance(item, dict)
    ]
    erros = [item for item in limpos if item["source"] and not item["href"] and not item["title"]]
    limpos = [item for item in limpos if item["title"] or item["href"]]
    resultado["results"] = limpos
    resultado["engine"] = next((item["source"] for item in limpos if item["source"]), "")
    if not limpos:
        resultado["error"] = erros[0]["source"] if erros else "A pesquisa não devolveu resultados."
        return resultado

    if usar_ia:
        texto = _web_summary(texto_pesquisa, limpos)
        if texto:
            resultado["text"] = texto
            resultado["ai"] = True
        else:
            resultado["notes"].append("Sem modelo configurado: excertos da web apresentados sem síntese.")

    excertos = [
        f"{item['title'] or _dominio(item['href'])} — {item['body']}"
        if item["body"]
        else (item["title"] or item["href"])
        for item in limpos[:6]
    ]
    resultado["sections"].append(
        {
            "kind": "text" if resultado["text"] else "list",
            "title": "Produtos e serviços (pesquisa web)",
            "text": resultado["text"],
            "items": excertos,
        }
    )
    resultado["sections"].append(
        {
            "kind": "table",
            "title": f"Fontes da pesquisa — «{texto_pesquisa}»" + (f" · motor: {resultado['engine']}" if resultado["engine"] else ""),
            "columns": ["Fonte", "Título", "Ligação"],
            "rows": [
                [_dominio(item["href"]) or item["source"] or "—", item["title"] or "—", item["href"] or "—"]
                for item in limpos[:8]
            ],
        }
    )
    return resultado


def _web_summary(query: str, results: Sequence[Dict[str, Any]]) -> str:
    """Síntese dos excertos pela IA (vazio quando não há modelo utilizável)."""
    excertos = "\n".join(
        f"- {item['title']} ({_dominio(item['href'])}): {item['body']}" for item in results[:6]
    )
    instrucao = (
        f"Consulta: {query}.\n"
        "Descreve, em 3 a 5 frases corridas, os produtos e serviços da empresa a partir destes excertos. "
        "Se os excertos não descreverem produtos ou serviços, escreve exatamente «Sem informação suficiente nas fontes consultadas.». "
        "Não uses listas nem markdown."
    )
    return _ask_model_sync(_WEB_SISTEMA, instrucao + "\n\nEXCERTOS:\n" + excertos, max_tokens=500)


def _ask_model_sync(system: str, prompt: str, *, max_tokens: int = 600) -> str:
    """Chamada à IA a partir de código síncrono (o PDF e a pré-visualização).

    Sem modelo configurado, ou dentro de um ciclo de eventos, devolve vazio: a
    alternativa factual (os excertos) é o que fica no relatório.
    """
    try:
        import asyncio  # noqa: PLC0415

        try:
            asyncio.get_running_loop()
            return ""
        except RuntimeError:
            pass
        from api import ontology_ai as ai  # noqa: PLC0415
        from api import people_360  # noqa: PLC0415

        backend, _note = people_360.resolve_backend(None, None)
        if backend.get("kind") != "cloud":
            return ""
        texto = asyncio.run(ai.ask_model(backend, system=system, prompt=prompt, max_tokens=max_tokens, temperature=0.2))
        return _text(texto, 1500)
    except Exception as exc:  # noqa: BLE001 - a IA nunca bloqueia o relatório
        logger.info("Estúdio: síntese da web sem IA (%s)", exc)
        return ""


# --------------------------------------------------------------------------
# Blocos
# --------------------------------------------------------------------------
def _block(block_type: str, title: str = "", **extra: Any) -> Dict[str, Any]:
    block: Dict[str, Any] = {
        "id": extra.pop("id", "") or _new_id("blk"),
        "type": block_type,
        "title": title,
        "text": extra.pop("text", ""),
        "prompt": extra.pop("prompt", ""),
        "source": extra.pop("source", ""),
        "dimensions": extra.pop("dimensions", []),
        "measures": extra.pop("measures", []),
        "filters": extra.pop("filters", {}),
        "search": extra.pop("search", ""),
        "chart": extra.pop("chart", ""),
        "limit": extra.pop("limit", 12),
        "top_n": extra.pop("top_n", 0),
        "width": extra.pop("width", 12),
        "format": extra.pop("format", ""),
        "empresa": extra.pop("empresa", ""),
        "query": extra.pop("query", ""),
        "site": extra.pop("site", ""),
    }
    block.update(extra)
    return block


def _filters(value: Any) -> Dict[str, Any]:
    """Filtros do bloco: escalares, listas ou `{min, max}` (como no Visualizador)."""
    if not isinstance(value, dict):
        if isinstance(value, str):
            parsed: Dict[str, Any] = {}
            for line in value.splitlines():
                if "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                key = _text(key, 80)
                if not key:
                    continue
                parts = [part.strip() for part in raw.split(",") if part.strip()]
                parsed[key] = parts[0] if len(parts) == 1 else parts
            return parsed
        return {}
    out: Dict[str, Any] = {}
    for key, raw in value.items():
        ident = _text(key, 80)
        if not ident:
            continue
        if isinstance(raw, (list, tuple, set)):
            values = [str(item).strip() for item in raw if str(item).strip()]
            if values:
                out[ident] = values[:50]
        elif isinstance(raw, dict):
            bounds = {key: raw[key] for key in ("min", "max", "gte", "lte") if raw.get(key) not in (None, "")}
            if bounds:
                out[ident] = bounds
        elif raw is not None and str(raw).strip():
            out[ident] = str(raw).strip()
    return out


def _normalise_block(raw: Any, source_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Valida um bloco. Campos que a fonte não tem são retirados (com nota)."""
    data = raw if isinstance(raw, dict) else {}
    block_type = _text(data.get("type"), 20).lower()
    if block_type not in BLOCK_TYPES:
        raise ValueError(f"Tipo de bloco inválido: {block_type or '(vazio)'}. Válidos: {', '.join(BLOCK_TYPES)}.")
    block = _block(block_type)
    block["id"] = _text(data.get("id"), 60) or block["id"]
    block["title"] = _text(data.get("title") or block.get("title"), MAX_TITLE)
    block["text"] = _long_text(data.get("text"))
    block["prompt"] = _long_text(data.get("prompt"), MAX_PROMPT)
    block["filters"] = _filters(data.get("filters"))
    block["search"] = _text(data.get("search"), 200)
    block["width"] = _int(data.get("width"), 12)
    if block["width"] not in WIDTHS:
        block["width"] = 12
    block["limit"] = max(1, min(_int(data.get("limit"), 12) or 12, MAX_ROWS))
    block["top_n"] = max(0, min(_int(data.get("top_n"), 0), MAX_ROWS))
    block["format"] = _text(data.get("format"), 20)

    if block_type in {"heading", "text", "note"}:
        if not block["title"] and not block["text"]:
            raise ValueError(f"O bloco «{BLOCK_LABELS[block_type]}» precisa de título ou texto.")
        return block

    if block_type == "ai":
        block["text"] = block["text"]
        block["prompt"] = block["prompt"]
        return block

    if block_type == "empresa":
        # A empresa pode vir do bloco ou do parâmetro do relatório (`{{empresa}}`);
        # exige-se em execução, não na gravação: o autor pode montar o modelo antes
        # de escolher a empresa.
        block["empresa"] = _text(data.get("empresa"), MAX_VAR_VALUE)
        block["limit"] = max(4, min(_int(data.get("limit"), MAX_FICHA_ROWS) or MAX_FICHA_ROWS, MAX_FICHA_ROWS))
        return block

    if block_type == "web":
        block["query"] = _text(data.get("query") or data.get("search"), 300)
        block["search"] = ""
        block["site"] = _text(data.get("site"), 160)
        block["limit"] = max(1, min(_int(data.get("limit"), 5) or 5, MAX_WEB_RESULTS))
        if not block["query"]:
            raise ValueError("O bloco de pesquisa web precisa do que pesquisar (ex.: «{{nome}} produtos e serviços»).")
        return block

    source_id = _text(data.get("source"), 80)
    source = source_map.get(source_id)
    if source_id and source is None:
        raise ValueError(f"Fonte desconhecida: {source_id}.")
    if source is None:
        raise ValueError(f"O bloco «{BLOCK_LABELS[block_type]}» precisa de uma fonte.")
    block["source"] = source_id

    valid_dimensions = {entry["id"] for entry in source["dimensions"]}
    valid_measures = {entry["id"] for entry in source["measures"]}
    dropped: List[str] = []
    dimensions: List[str] = []
    for item in _as_list(data.get("dimensions"), MAX_DIMENSIONS + 4):
        if item in valid_dimensions:
            dimensions.append(item)
        else:
            dropped.append(item)
    measures: List[str] = []
    for item in _as_list(data.get("measures"), MAX_MEASURES + 4):
        if item in valid_measures:
            measures.append(item)
        else:
            dropped.append(item)
    block["dimensions"] = dimensions[:MAX_DIMENSIONS]
    block["measures"] = measures[:MAX_MEASURES]

    if block_type == "kpi":
        if not block["measures"]:
            block["measures"] = ["contagem"] if "contagem" in valid_measures else block["measures"]
        if not block["measures"]:
            raise ValueError("Os indicadores precisam de pelo menos uma medida da fonte.")
        block["measures"] = block["measures"][:MAX_KPI]
        block["dimensions"] = []
    elif block_type == "chart":
        chart = _text(data.get("chart"), 20).lower()
        if chart not in CHART_KINDS:
            raise ValueError(f"Tipo de gráfico inválido: {chart or '(vazio)'}. Válidos: {', '.join(CHART_KINDS)}.")
        block["chart"] = chart
        if not block["dimensions"]:
            raise ValueError("O gráfico precisa de pelo menos uma dimensão.")
        if not block["measures"]:
            block["measures"] = ["contagem"] if "contagem" in valid_measures else block["measures"]
        if not block["measures"]:
            raise ValueError("O gráfico precisa de pelo menos uma medida.")
        block["measures"] = block["measures"][:1] if chart in {"donut", "pie", "line", "area"} else block["measures"][:2]
    elif block_type == "table":
        if not block["dimensions"]:
            raise ValueError("A tabela precisa de pelo menos uma dimensão.")
        if not block["measures"]:
            block["measures"] = ["contagem"] if "contagem" in valid_measures else block["measures"]
        if not block["measures"]:
            raise ValueError("A tabela precisa de pelo menos uma medida.")
        block["limit"] = max(1, min(block["limit"], MAX_ROWS))
    elif block_type == "graph":
        if len(block["dimensions"]) != 2:
            raise ValueError("O grafo precisa de duas dimensões (origem e destino).")
        if not block["measures"]:
            block["measures"] = ["contagem"] if "contagem" in valid_measures else block["measures"]
        if not block["measures"]:
            raise ValueError("O grafo precisa de pelo menos uma medida.")
        block["measures"] = block["measures"][:1]
        block["limit"] = max(2, min(block["limit"], MAX_GRAPH_EDGES))

    if dropped:
        block["_dropped"] = dropped[:8]
    return block


def _clean_block(block: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in block.items() if not key.startswith("_")}


# --------------------------------------------------------------------------
# Modelos (templates) prontos a usar
# --------------------------------------------------------------------------
def _template(
    template_id: str,
    name: str,
    description: str,
    *,
    icon: str,
    tags: Sequence[str],
    blocks: Sequence[Dict[str, Any]],
    subtitle: str = "",
    vars: Sequence[Dict[str, str]] = (),
) -> Dict[str, Any]:
    return {
        "id": template_id,
        "name": name,
        "description": description,
        "subtitle": subtitle,
        "icon": icon,
        "tags": list(tags),
        "vars": [dict(item) for item in vars],
        "blocks": [dict(block) for block in blocks],
    }


#: Parâmetros do modelo «relatório de empresa»: muda-se a empresa e o resto do
#: relatório (filtros, variáveis `{{nif}}`/`{{cae}}`/`{{cpv}}`) segue.
VAR_EMPRESA: Tuple[Dict[str, str], ...] = (
    {
        "id": "empresa",
        "label": "Empresa (NIF ou nome)",
        "hint": "NIF de 9 dígitos (recomendado) ou o nome como consta no cadastro. É o único campo a mudar entre relatórios.",
        "required": "1",
    },
    {
        "id": "nome",
        "label": "Nome a usar no relatório",
        "hint": "Opcional: se ficar vazio, é lido do cadastro da empresa.",
    },
)


TEMPLATES: List[Dict[str, Any]] = [
    _template(
        "executivo",
        "Sumário executivo",
        "Uma página para decidir: indicadores, evolução, maiores adjudicatários e um sumário escrito pela IA.",
        subtitle="Contratação pública — leitura rápida",
        icon="gauge",
        tags=["executivo", "contratação"],
        blocks=[
            _block("heading", "Sumário executivo", text="O essencial do período em análise."),
            _block("kpi", "Indicadores gerais", source="contrato", measures=["contagem", "soma_preco", "media_preco"]),
            _block("chart", "Evolução por ano", source="contrato", chart="area",
                   dimensions=["ano"], measures=["soma_preco"], limit=14),
            _block("chart", "Maiores adjudicatários", source="contrato", chart="bar-h",
                   dimensions=["adjudicatario"], measures=["soma_preco"], top_n=10, limit=25, width=6),
            _block("chart", "Tipo de contrato", source="contrato", chart="donut",
                   dimensions=["tipo_contrato"], measures=["contagem"], limit=8, width=6),
            _block("ai", "Leitura dos dados", prompt="Escreve a leitura executiva destes indicadores."),
            _block("note", "Nota metodológica",
                   text="Valores apurados a partir dos contratos publicados na plataforma. As agregações são calculadas na fonte e não extrapoladas de amostras."),
        ],
    ),
    _template(
        "mercado-cpv",
        "Mercado por CPV",
        "Onde está o dinheiro por classificação europeia: top CPV, valor médio e peso de cada região.",
        subtitle="Contratação por categoria",
        icon="tags",
        tags=["compras", "cpv"],
        blocks=[
            _block("heading", "Mercado por CPV"),
            _block("kpi", "Totais", source="cpv", measures=["contagem", "valor", "valor_medio"]),
            _block("chart", "Top CPV por valor", source="cpv", chart="bar-h",
                   dimensions=["cpv"], measures=["valor"], top_n=15, limit=40, width=6),
            _block("chart", "CPV por número de contratos", source="cpv", chart="bar-h",
                   dimensions=["cpv"], measures=["contagem"], top_n=15, limit=40, width=6),
            _block("chart", "Peso das regiões", source="regiao", chart="donut",
                   dimensions=["regiao"], measures=["valor"], limit=8),
            _block("ai", "Destaques", prompt="Destaca os CPV e as regiões mais relevantes."),
        ],
    ),
    _template(
        "evolucao",
        "Evolução temporal",
        "Séries comparáveis por ano, tipo de contrato e procedimento, com tabela anual.",
        subtitle="Contratação pública ao longo do tempo",
        icon="trending-up",
        tags=["séries", "contratação"],
        blocks=[
            _block("heading", "Evolução do período"),
            _block("kpi", "Volumes", source="contrato", measures=["contagem", "soma_preco", "media_preco"]),
            _block("chart", "Valor por ano", source="contrato", chart="line",
                   dimensions=["ano"], measures=["soma_preco"], limit=20, width=6),
            _block("chart", "Contratos por ano", source="contrato", chart="bar",
                   dimensions=["ano"], measures=["contagem"], limit=20, width=6),
            _block("table", "Ano × tipo de contrato", source="contrato",
                   dimensions=["ano", "tipo_contrato"], measures=["contagem", "soma_preco"], limit=40),
        ],
    ),
    _template(
        "geografia",
        "Distribuição geográfica",
        "Como se distribui o valor e o número de contratos por região e local de execução.",
        subtitle="Leitura territorial",
        icon="map",
        tags=["regiões", "território"],
        blocks=[
            _block("heading", "Distribuição geográfica"),
            _block("kpi", "Totais", source="regiao", measures=["contagem", "valor", "valor_medio"]),
            _block("chart", "Valor por região", source="regiao", chart="bar-h",
                   dimensions=["regiao"], measures=["valor"], top_n=12, limit=30),
            _block("chart", "Contratos por região", source="regiao", chart="donut",
                   dimensions=["regiao"], measures=["contagem"], limit=8),
            _block("table", "Região × ano", source="regiao", dimensions=["regiao", "ano"],
                   measures=["contagem", "valor"], limit=40),
        ],
    ),
    _template(
        "entidades",
        "Entidades e relações",
        "Quem compra, quem vende e as relações entre ambos — com grafo das ligações mais fortes.",
        subtitle="Mapa de partes",
        icon="network",
        tags=["entidades", "grafo"],
        blocks=[
            _block("heading", "Entidades e relações"),
            _block("kpi", "Partes envolvidas", source="contrato",
                   measures=["contagem", "soma_preco", "distintos_adjudicatario"]),
            _block("chart", "Maiores adjudicatários", source="contrato", chart="bar-h",
                   dimensions=["adjudicatario"], measures=["soma_preco"], top_n=12, limit=30, width=6),
            _block("chart", "Maiores adjudicantes", source="contrato", chart="bar-h",
                   dimensions=["adjudicante"], measures=["soma_preco"], top_n=12, limit=30, width=6),
            _block("graph", "Relações adjudicante ↔ adjudicatário", source="contrato",
                   dimensions=["adjudicante", "adjudicatario"], measures=["soma_preco"], limit=20),
            _block("table", "Adjudicatário × ano", source="contrato",
                   dimensions=["adjudicatario", "ano"], measures=["contagem", "soma_preco"], limit=30),
        ],
    ),
    _template(
        "mercados",
        "Mercados e notícias",
        "Volume de notícias, publicadores, sentimento e instrumentos mais mencionados.",
        subtitle="Inteligência de mercados",
        icon="newspaper",
        tags=["mercados", "notícias"],
        blocks=[
            _block("heading", "Mercados e notícias"),
            _block("kpi", "Cobertura", source="noticia", measures=["contagem", "distintos_ticker", "distintos_publicador"]),
            _block("chart", "Notícias por mês", source="noticia", chart="line",
                   dimensions=["publicado"], measures=["contagem"], limit=24),
            _block("chart", "Sentimento", source="noticia", chart="donut",
                   dimensions=["sentimento"], measures=["contagem"], limit=6, width=6),
            _block("chart", "Publicadores", source="noticia", chart="bar-h",
                   dimensions=["publicador"], measures=["contagem"], top_n=10, limit=25, width=6),
            _block("table", "Instrumento × sentimento", source="noticia",
                   dimensions=["ticker", "sentimento"], measures=["contagem"], limit=30),
        ],
    ),
    _template(
        "dossie",
        "Dossiê completo",
        "Relatório extenso: capa, sumário, indicadores, gráficos, grafo, tabelas e notas de método.",
        subtitle="Documento de referência",
        icon="book-open",
        tags=["completo", "referência"],
        blocks=[
            _block("heading", "Enquadramento", text="Objeto, âmbito e período do dossiê."),
            _block("ai", "Sumário executivo", prompt="Escreve o sumário executivo do dossiê a partir dos dados."),
            _block("kpi", "Indicadores gerais", source="contrato",
                   measures=["contagem", "soma_preco", "media_preco", "distintos_adjudicatario"]),
            _block("chart", "Evolução por ano", source="contrato", chart="area",
                   dimensions=["ano"], measures=["soma_preco"], limit=20),
            _block("chart", "Top CPV", source="cpv", chart="bar-h",
                   dimensions=["cpv"], measures=["valor"], top_n=12, limit=30, width=6),
            _block("chart", "Regiões", source="regiao", chart="donut",
                   dimensions=["regiao"], measures=["valor"], limit=8, width=6),
            _block("graph", "Relações entre partes", source="contrato",
                   dimensions=["adjudicante", "adjudicatario"], measures=["soma_preco"], limit=18),
            _block("table", "Detalhe por ano e tipo", source="contrato",
                   dimensions=["ano", "tipo_contrato"], measures=["contagem", "soma_preco"], limit=50),
            _block("note", "Método e limites",
                   text="As agregações resultam das fontes indexadas na plataforma à data de geração. Onde a fonte não tem o campo, o grupo aparece como «Não especificado»."),
        ],
    ),
    _template(
        "concorrencia",
        "Concorrência (uma empresa)",
        "A empresa, o que vende e com quem compete: ficha 360 (cadastro e CAE, sócios e gerentes, pessoas, riscos), contratos por CPV, clientes, concorrentes nos mesmos CPV e empresas do mesmo CAE. Muda-se a empresa e o relatório refaz-se.",
        subtitle="Empresa, CPV, CAE, sócios, pessoas e risco",
        icon="swords",
        tags=["empresa", "concorrência", "cpv", "cae", "risco"],
        vars=VAR_EMPRESA,
        blocks=[
            _block("heading", "Concorrência — {{nome}}",
                   text="Posição da empresa na contratação pública: cadastro e CAE, CPV onde ganha, clientes, concorrentes, sócios e gerentes, pessoas com cargos e sinais de risco."),
            _block("empresa", "Ficha 360 da empresa", empresa="{{empresa}}"),
            _block("kpi", "Contratos da empresa", source="contrato", filters={"adjudicatario_nif": "{{nif}}"},
                   measures=["contagem", "soma_preco", "media_preco", "distintos_cpv_codigo"]),
            _block("chart", "Onde ganha (CPV)", source="contrato", chart="bar-h",
                   dimensions=["cpv_codigo"], measures=["soma_preco"], filters={"adjudicatario_nif": "{{nif}}"},
                   top_n=10, limit=25, width=6),
            _block("chart", "Evolução por ano", source="contrato", chart="bar",
                   dimensions=["ano"], measures=["soma_preco"], filters={"adjudicatario_nif": "{{nif}}"},
                   limit=16, width=6),
            _block("chart", "Como contrata (procedimento)", source="contrato", chart="donut",
                   dimensions=["procedimento"], measures=["contagem"], filters={"adjudicatario_nif": "{{nif}}"},
                   limit=6, width=6),
            _block("graph", "Quem compra à empresa", source="contrato",
                   dimensions=["adjudicante", "adjudicatario"], measures=["soma_preco"],
                   filters={"adjudicatario_nif": "{{nif}}"}, limit=12, width=6),
            _block("table", "Concorrentes no CPV principal", source="contrato",
                   dimensions=["adjudicatario"], measures=["contagem", "soma_preco"],
                   filters={"cpv_codigo": "{{cpv}}"}, limit=12),
            _block("chart", "Onde se compra este CPV", source="regiao", chart="donut",
                   dimensions=["regiao"], measures=["valor"], filters={"cpv_codigo": "{{cpv}}"}, limit=8),
            _block("table", "Empresas no mesmo CAE", source="firma",
                   dimensions=["nome", "concelho", "situacao"], measures=["contagem", "soma_score"],
                   filters={"cae": "{{cae}}"}, limit=15),
            _block("ai", "Leitura da concorrência",
                   prompt="Compara a empresa com o mercado: onde ganha, de quem depende, como contrata e que sinais de risco apresenta. Sem inventar números."),
            _block("note", "Método e limites",
                   text="Contratos do Portal BASE indexados na plataforma à data de geração; registos de cadastro, RNPC (CAE), INPI, registo comercial e CIRE obtidos na ficha da empresa. A ficha trata os valores de amostra como amostra e distingue insolvências de simples menções em processos de terceiros."),
        ],
    ),
    _template(
        "area-cae",
        "Área de CAE e da empresa",
        "Olha primeiro para a área de atividade (CAE): quantas empresas, onde estão, em que situação registal e quem contrata no setor. Depois, a empresa dentro dele — CPV, clientes, concorrência — e os produtos e serviços descritos nas fontes web.",
        subtitle="Setor de atividade (CAE) e a empresa dentro dele",
        icon="layers",
        tags=["cae", "setor", "empresa", "web", "produtos"],
        vars=VAR_EMPRESA,
        blocks=[
            _block("heading", "Área de CAE e a empresa",
                   text="A área de atividade (CAE) da empresa: dimensão do setor, implantação territorial, situação registal e contratação — e, no fim, os produtos e serviços da empresa descritos publicamente."),
            _block("empresa", "Ficha 360 da empresa", empresa="{{empresa}}"),
            _block("kpi", "Setor no CAE principal", source="firma", filters={"cae": "{{cae}}"},
                   measures=["contagem", "distintos_nif_empresa", "media_score"]),
            _block("chart", "CAE com mais empresas", source="firma", chart="bar-h",
                   dimensions=["cae"], measures=["distintos_nif_empresa"], top_n=12, limit=30, width=6),
            _block("chart", "Situação registal no setor", source="firma", chart="donut",
                   dimensions=["situacao"], measures=["contagem"], filters={"cae": "{{cae}}"}, limit=6, width=6),
            _block("chart", "Onde estão as empresas do setor", source="firma", chart="bar-h",
                   dimensions=["concelho"], measures=["contagem"], filters={"cae": "{{cae}}"}, top_n=10, limit=25, width=6),
            _block("table", "Empresas do mesmo CAE", source="firma",
                   dimensions=["nome", "concelho", "situacao"], measures=["contagem", "soma_score"],
                   filters={"cae": "{{cae}}"}, limit=15),
            _block("table", "Contratos da empresa por tipo e procedimento", source="contrato",
                   dimensions=["tipo_contrato", "procedimento"], measures=["contagem", "soma_preco"],
                   filters={"adjudicatario_nif": "{{nif}}"}, limit=20),
            _block("chart", "CPV da empresa", source="contrato", chart="bar-h",
                   dimensions=["cpv_codigo"], measures=["soma_preco"], filters={"adjudicatario_nif": "{{nif}}"},
                   top_n=10, limit=25),
            _block("web", "Produtos e serviços (pesquisa web)", query="{{nome}} produtos e serviços", limit=6),
            _block("ai", "Análise do setor e da empresa",
                   prompt="Descreve o setor (CAE) e o posicionamento da empresa nele, incluindo o que os excertos da web dizem dos seus produtos e serviços. Só com os dados apresentados."),
            _block("note", "Método e limites",
                   text="O setor é lido a partir dos registos do RNPC indexados (firmas e CAE) e a empresa a partir do cadastro, contratos, registo comercial, CIRE e INPI. Os produtos e serviços vêm de pesquisa web: são excertos de terceiros, apresentados com a fonte, e não substituem o catálogo oficial da empresa."),
        ],
    ),
    _template(
        "personalizado",
        "Em branco",
        "Começa do zero: junta os blocos que precisares, na ordem que quiseres.",
        subtitle="Do zero",
        icon="file-plus",
        tags=["livre"],
        blocks=[],
    ),
]

TEMPLATES_BY_ID: Dict[str, Dict[str, Any]] = {item["id"]: item for item in TEMPLATES}


def _resolve_blocks(blocks: Sequence[Dict[str, Any]], source_map: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Mantém só blocos desenháveis com as fontes de agora (e diz o que caiu)."""
    out: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for raw in blocks:
        try:
            out.append(_clean_block(_normalise_block(raw, source_map)))
        except ValueError as exc:
            warnings.append(f"Bloco retirado ({raw.get('title') or raw.get('type')}): {exc}")
    return out, warnings


def templates(scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Modelos prontos, já validados contra as fontes disponíveis."""
    source_map = _source_map(scope)
    items: List[Dict[str, Any]] = []
    for template in TEMPLATES:
        blocks, warnings = _resolve_blocks(template["blocks"], source_map)
        items.append(
            {
                "id": template["id"],
                "name": template["name"],
                "description": template["description"],
                "subtitle": template["subtitle"],
                "icon": template["icon"],
                "tags": list(template["tags"]),
                "vars": [dict(item) for item in template.get("vars") or []],
                "blocks": blocks,
                "block_count": len(blocks),
                "warnings": warnings,
                "available": template["id"] == "personalizado" or bool(blocks),
            }
        )
    return {"templates": items, "total": len(items), "sources": len(source_map)}


def template(template_id: str, scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = _text(template_id, 60).lower()
    if key not in TEMPLATES_BY_ID:
        raise KeyError(f"Modelo desconhecido: {template_id}.")
    for item in templates(scope)["templates"]:
        if item["id"] == key:
            return item
    raise KeyError(f"Modelo desconhecido: {template_id}.")  # pragma: no cover - defensivo


# --------------------------------------------------------------------------
# Relatórios
# --------------------------------------------------------------------------
def _empty_publication() -> Dict[str, Any]:
    return {
        "site": {"published": False, "package_id": "", "price": 0.0, "list_price": 0.0, "at": "", "by": ""},
        "loja": {"published": False, "product_id": "", "price": 0.0, "list_price": 0.0, "at": "", "by": ""},
    }


def _publication_state(doc: Dict[str, Any]) -> Dict[str, Any]:
    raw = doc.get("publication") if isinstance(doc.get("publication"), dict) else {}
    state = _empty_publication()
    for target in TARGETS:
        current = raw.get(target) if isinstance(raw.get(target), dict) else {}
        state[target].update(
            {
                "published": bool(current.get("published")),
                "price": _float(current.get("price")),
                "list_price": _float(current.get("list_price")),
                "at": _text(current.get("at"), 40),
                "by": _text(current.get("by"), 160),
            }
        )
        if target == "site":
            state[target]["package_id"] = _text(current.get("package_id"), 80)
        else:
            state[target]["product_id"] = _text(current.get("product_id"), 80)
    return state


def new_report(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Relatório novo — a partir de um modelo (ou vazio), sem o gravar."""
    source_map = _source_map()
    template_id = _text((payload or {}).get("template") or (payload or {}).get("template_id"), 60).lower()
    base_blocks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if template_id:
        try:
            model = template(template_id)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        base_blocks = model["blocks"]
        warnings = list(model["warnings"])
        name = _text(payload.get("title") or model["name"], MAX_TITLE)
        subtitle = _text(payload.get("subtitle") or model["subtitle"], MAX_TITLE)
        description = _long_text(payload.get("description") or model["description"], 600)
        tags = _as_list(payload.get("tags") or model["tags"], 12)
    else:
        name = _text(payload.get("title"), MAX_TITLE)
        subtitle = _text(payload.get("subtitle"), MAX_TITLE)
        description = _long_text(payload.get("description"), 600)
        tags = _as_list(payload.get("tags"), 12)
    if not name:
        raise ValueError("O relatório precisa de um título.")

    blocks = copy.deepcopy(base_blocks)
    if payload.get("blocks"):
        blocks, extra = _resolve_blocks(payload["blocks"], source_map)
        warnings.extend(extra)

    doc = {
        "id": _new_id("rep"),
        "title": name,
        "subtitle": subtitle,
        "description": description,
        "summary": _long_text(payload.get("summary"), MAX_TEXT),
        "template": template_id,
        "tags": tags,
        "theme": _text(payload.get("theme") or "iq", 40),
        "targets_note": _long_text(payload.get("targets_note"), 400),
        "vars": normalise_vars(payload.get("vars"), template_id),
        "blocks": [_clean_block(block) for block in blocks],
        "publication": _empty_publication(),
        "files": [],
        "created_at": _now(),
        "updated_at": _now(),
        "created_by": actor,
        "updated_by": actor,
    }
    return {"report": report_view(doc, include_internal=True), "warnings": warnings}


def normalise_report(payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Valida o relatório inteiro (usado ao guardar)."""
    doc = copy.deepcopy(existing) if existing else {}
    title = _text(payload.get("title"), MAX_TITLE) if "title" in payload else _text(doc.get("title"), MAX_TITLE)
    if not title:
        raise ValueError("O relatório precisa de um título.")
    doc["title"] = title
    if "subtitle" in payload:
        doc["subtitle"] = _text(payload.get("subtitle"), MAX_TITLE)
    if "description" in payload:
        doc["description"] = _long_text(payload.get("description"), 600)
    if "summary" in payload:
        doc["summary"] = _long_text(payload.get("summary"), MAX_TEXT)
    if "tags" in payload:
        doc["tags"] = _as_list(payload.get("tags"), 12)
    if "theme" in payload:
        doc["theme"] = _text(payload.get("theme") or "iq", 40)
    if "targets_note" in payload:
        doc["targets_note"] = _long_text(payload.get("targets_note"), 400)
    if "template" in payload:
        doc["template"] = _text(payload.get("template"), 60).lower()
    if "blocks" in payload:
        raw_blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
        if len(raw_blocks) > MAX_BLOCKS:
            raise ValueError(f"Demasiados blocos ({len(raw_blocks)}); o máximo é {MAX_BLOCKS}.")
        source_map = _source_map()
        blocks, warnings = _resolve_blocks(raw_blocks, source_map)
        if raw_blocks and not blocks:
            # Nenhum bloco sobreviveu: é erro de quem montou, não um relatório vazio.
            raise ValueError(warnings[0] if warnings else "Nenhum bloco válido.")
        doc["blocks"] = [_clean_block(block) for block in blocks]
        doc["_warnings"] = warnings
    if "vars" in payload:
        doc["vars"] = normalise_vars(payload.get("vars"), _text(doc.get("template"), 60))
    return doc


def report_view(doc: Dict[str, Any], *, include_internal: bool = False) -> Dict[str, Any]:
    """Vista do relatório para a interface."""
    publication = _publication_state(doc)
    blocks = [_clean_block(block) for block in (doc.get("blocks") or [])]
    view: Dict[str, Any] = {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "subtitle": doc.get("subtitle") or "",
        "description": doc.get("description") or "",
        "summary": doc.get("summary") or "",
        "template": doc.get("template") or "",
        "tags": list(doc.get("tags") or []),
        "theme": doc.get("theme") or "iq",
        "targets_note": doc.get("targets_note") or "",
        "vars": normalise_vars(doc.get("vars"), doc.get("template") or ""),
        "vars_spec": vars_spec(doc.get("template") or ""),
        "blocks": blocks,
        "publication": publication,
        "published": any(publication[target]["published"] for target in TARGETS),
        "channels": [target for target in TARGETS if publication[target]["published"]],
        "files": [
            {key: value for key, value in item.items() if key != "path"}
            for item in (doc.get("files") or [])
            if isinstance(item, dict)
        ],
        "created_at": doc.get("created_at") or "",
        "updated_at": doc.get("updated_at") or "",
        "created_by": doc.get("created_by") or "",
        "updated_by": doc.get("updated_by") or "",
        "stats": {
            "blocks": len(blocks),
            "charts": len([block for block in blocks if block.get("type") in {"chart", "graph"}]),
            "tables": len([block for block in blocks if block.get("type") == "table"]),
            "ai": len([block for block in blocks if block.get("type") == "ai"]),
            "has_pdf": bool(doc.get("files")),
            "sources": sorted({block.get("source") for block in blocks if block.get("source")}),
        },
    }
    view["status"] = "publicado" if view["published"] else "rascunho"
    view["status_label"] = REPORT_LABELS[view["status"]]
    view["status_style"] = REPORT_STYLE[view["status"]]
    if include_internal:
        view["auto_key"] = auto_key(str(doc.get("id") or ""))
    return view


def _reports() -> List[Dict[str, Any]]:
    return store.load().setdefault("studio_reports", [])


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    key = _text(report_id, 80)
    return next((doc for doc in _reports() if str(doc.get("id")) == key), None)


def get_report_view(report_id: str, *, include_internal: bool = False) -> Optional[Dict[str, Any]]:
    doc = get_report(report_id)
    return report_view(doc, include_internal=include_internal) if doc else None


def list_reports(*, q: str = "", status: str = "", template: str = "", channel: str = "", limit: int = 200) -> Dict[str, Any]:
    needle = _text(q, 120).lower()
    wanted_status = _text(status, 20).lower()
    wanted_template = _text(template, 60).lower()
    wanted_channel = _text(channel, 20).lower()
    items: List[Dict[str, Any]] = []
    for doc in _reports():
        view = report_view(doc)
        if needle and needle not in f"{view['title']} {view['subtitle']} {view['description']}".lower():
            continue
        if wanted_status and view["status"] != wanted_status:
            continue
        if wanted_template and view["template"] != wanted_template:
            continue
        if wanted_channel and wanted_channel not in view["channels"]:
            continue
        items.append(view)
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    items = items[: max(1, min(_int(limit, 200), MAX_REPORTS))]
    return {
        "items": items,
        "total": len(items),
        "labels": REPORT_LABELS,
        "styles": REPORT_STYLE,
        "templates": [{"id": item["id"], "name": item["name"]} for item in TEMPLATES],
        "targets": [{"id": target, "label": TARGET_LABELS[target]} for target in TARGETS],
        "stats": {
            "total": len(_reports()),
            "drafts": len([doc for doc in _reports() if not report_view(doc)["published"]]),
            "published": len([doc for doc in _reports() if report_view(doc)["published"]]),
            "with_pdf": len([doc for doc in _reports() if doc.get("files")]),
        },
    }


def create_report(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Cria um relatório — a partir de um modelo (blocos prontos) ou do zero."""
    if payload.get("template") and not payload.get("blocks"):
        proposal = new_report(payload, actor)
        view = proposal["report"]
        seed = {
            key: view.get(key)
            for key in ("title", "subtitle", "description", "summary", "tags", "theme", "targets_note", "template", "vars", "blocks")
        }
        saved = save_report(seed, actor)
        saved["warnings"] = list(proposal.get("warnings") or []) + list(saved.get("warnings") or [])
        return saved
    return save_report(payload, actor)


def save_report(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Cria ou atualiza um relatório (com validação das fontes)."""
    with store._lock:  # noqa: SLF001 - o documento é partilhado com os pedidos
        data = store.load()
        items: List[Dict[str, Any]] = data.setdefault("studio_reports", [])
        report_id = _text(payload.get("id"), 80)
        existing = next((doc for doc in items if str(doc.get("id")) == report_id), None) if report_id else None
        if report_id and existing is None:
            raise KeyError(f"Relatório {report_id} não encontrado.")
        if existing is None and len(items) >= MAX_REPORTS:
            raise ValueError("Demasiados relatórios no estúdio.")
        doc = normalise_report(payload, existing)
        warnings = doc.pop("_warnings", [])
        if existing is None:
            doc["id"] = doc.get("id") or _new_id("rep")
            doc["created_at"] = _now()
            doc["created_by"] = actor
            doc["publication"] = doc.get("publication") or _empty_publication()
            doc["files"] = doc.get("files") or []
            items.insert(0, doc)
            action = "studio.report.created"
        else:
            doc["id"] = existing["id"]
            doc["created_at"] = existing.get("created_at") or _now()
            doc["created_by"] = existing.get("created_by") or actor
            doc["publication"] = existing.get("publication") or _empty_publication()
            doc["files"] = existing.get("files") or []
            items[items.index(existing)] = doc
            action = "studio.report.saved"
        doc["updated_at"] = _now()
        doc["updated_by"] = actor
        store._log(data, action, actor=actor, detail=f"Relatório «{doc.get('title')}»")  # noqa: SLF001
        store._write_store(data)  # noqa: SLF001
    return {"report": report_view(doc, include_internal=True), "warnings": warnings}


def delete_report(report_id: str, actor: str = "") -> bool:
    with store._lock:  # noqa: SLF001
        data = store.load()
        items: List[Dict[str, Any]] = data.setdefault("studio_reports", [])
        doc = next((item for item in items if str(item.get("id")) == str(report_id)), None)
        if doc is None:
            return False
        items.remove(doc)
        store._log(data, "studio.report.deleted", actor=actor, detail=f"Relatório «{doc.get('title')}»")  # noqa: SLF001
        store._write_store(data)  # noqa: SLF001
    return True


def duplicate_report(report_id: str, actor: str = "", title: str = "") -> Dict[str, Any]:
    doc = get_report(report_id)
    if doc is None:
        raise KeyError(f"Relatório {report_id} não encontrado.")
    clone = {
        "title": _text(title, MAX_TITLE) or f"{doc.get('title')} (cópia)",
        "subtitle": doc.get("subtitle") or "",
        "description": doc.get("description") or "",
        "summary": doc.get("summary") or "",
        "template": doc.get("template") or "",
        "tags": list(doc.get("tags") or []),
        "theme": doc.get("theme") or "iq",
        # A cópia herda os parâmetros: é assim que se faz o mesmo relatório para
        # outra empresa — duplicar e mudar o NIF.
        "vars": dict(doc.get("vars") or {}),
        "blocks": copy.deepcopy(doc.get("blocks") or []),
    }
    saved = save_report(clone, actor)
    return saved


def context_vars(doc: Optional[Dict[str, Any]], scope: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Variáveis do relatório: as do autor e as que se calculam da empresa.

    `{{empresa}}` é o que o autor escreve (NIF ou nome); `{{nif}}`, `{{nome}}`,
    `{{cae}}`, `{{cpv}}` e `{{site}}` são resolvidos a partir da ficha, para que
    os blocos de mercado possam seguir a empresa sem trabalho manual.
    """
    mapping = {chave: _text(valor, MAX_VAR_VALUE) for chave, valor in ((doc or {}).get("vars") or {}).items()}
    empresa = mapping.get("empresa") or mapping.get("nif") or ""
    if not empresa:
        return mapping
    nif = empresa_nif(empresa)
    if not nif:
        return mapping
    mapping.setdefault("nif", nif)
    try:
        ficha = empresa_ficha(nif, scope, nome=mapping.get("nome") or "")
    except Exception as exc:  # noqa: BLE001 - sem ficha os tokens ficam vazios
        logger.warning("Estúdio: variáveis de %s não resolvidas (%s)", nif, exc)
        return mapping
    for chave, valor in (("nome", ficha.get("nome")), ("cae", ficha.get("cae")), ("site", ficha.get("site"))):
        if valor and not mapping.get(chave):
            mapping[chave] = _text(valor, MAX_VAR_VALUE)
    cpv = next(iter(ficha.get("cpvs") or []), "")
    if cpv and not mapping.get("cpv"):
        mapping["cpv"] = _text(cpv, MAX_VAR_VALUE)
    return mapping


def _block_query(block: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dataset": block.get("source"),
        "dimensions": list(block.get("dimensions") or []),
        "measures": list(block.get("measures") or []),
        "filters": dict(block.get("filters") or {}),
        "search": block.get("search") or None,
        "limit": _int(block.get("limit"), 12) or 12,
        "top_n": _int(block.get("top_n"), 0) or None,
    }


def _graph_from(result: Dict[str, Any], limit: int = MAX_GRAPH_EDGES) -> Dict[str, Any]:
    """Converte o resultado de duas dimensões em nós e arestas de um grafo."""
    dimensions = result.get("dimensions") or []
    measures = result.get("measures") or []
    if len(dimensions) < 2 or not measures:
        return {"nodes": [], "edges": [], "measure": "", "note": "O grafo precisa de duas dimensões e uma medida."}
    origin, target = str(dimensions[0]["id"]), str(dimensions[1]["id"])
    measure = str(measures[0]["id"])
    nodes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in (result.get("rows") or [])[: max(1, limit) * 3]:
        source_label = str(row.get(origin) or "—")
        target_label = str(row.get(target) or "—")
        if source_label == "—" and target_label == "—":
            continue
        value = row.get(measure)
        value = float(value) if isinstance(value, (int, float)) else 0.0
        key = (source_label, target_label)
        edge = edges.get(key)
        if edge is None:
            edges[key] = {"source": source_label, "target": target_label, "value": value}
        else:
            edge["value"] += value
        nodes.setdefault(("source", source_label), {"id": source_label, "side": "source", "value": 0.0})
        nodes.setdefault(("target", target_label), {"id": target_label, "side": "target", "value": 0.0})
        nodes[("source", source_label)]["value"] += value
        nodes[("target", target_label)]["value"] += value
    ordered = sorted(edges.values(), key=lambda item: item["value"], reverse=True)[: max(1, limit)]
    keep = {entry["source"] for entry in ordered} | {entry["target"] for entry in ordered}
    return {
        "nodes": [node for node in nodes.values() if node["id"] in keep][: 2 * max(1, limit)],
        "edges": ordered,
        "measure": measure,
        "origin": origin,
        "target": target,
        "labels": {"origin": dimensions[0].get("label"), "target": dimensions[1].get("label")},
    }


def run_block(block: Dict[str, Any], scope: Optional[Dict[str, Any]] = None, *, mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Corre a consulta de um bloco (ou devolve o texto, nos blocos de texto).

    `mapping` traz as variáveis do relatório: um bloco com `{{empresa}}` no filtro
    é resolvido antes de correr, para que o mesmo modelo sirva qualquer empresa.
    """
    if mapping is not None:
        # Um token por resolver não pode chegar à consulta nem ao NIF: com o mapa
        # vazio (`None` é "não sei"), o token desaparece em vez de virar pesquisa.
        block = apply_vars(block, mapping)
    block_type = str(block.get("type") or "")
    if block_type == "empresa":
        alvo = _text(block.get("empresa") or (mapping or {}).get("empresa") or (mapping or {}).get("nif"), MAX_VAR_VALUE)
        if not alvo or "{{" in alvo:
            return {
                "type": block_type,
                "id": block.get("id"),
                "title": block.get("title"),
                "width": block.get("width") or 12,
                "ficha": {},
                "kpis": [],
                "sections": [],
                "error": (
                    "Sem empresa: preencha o parâmetro «Empresa» do relatório (NIF ou nome) ou o campo do bloco. "
                    "A ficha 360 não é calculada sem uma empresa identificada."
                ),
                "notes": [],
            }
        ficha = empresa_ficha(alvo, scope, nome=(mapping or {}).get("nome") or "")
        return {
            "type": block_type,
            "id": block.get("id"),
            "title": block.get("title"),
            "width": block.get("width") or 12,
            "ficha": ficha,
            "kpis": ficha.get("kpis") or [],
            "sections": ficha.get("sections") or [],
            "error": ficha.get("error"),
            "notes": list(ficha.get("avisos") or []),
        }
    if block_type == "web":
        dados = web_products(block.get("query") or block.get("search"), limit=_int(block.get("limit"), 5) or 5, site=block.get("site") or "")
        return {
            "type": block_type,
            "id": block.get("id"),
            "title": block.get("title"),
            "width": block.get("width") or 12,
            "text": dados.get("text") or "",
            "query": dados.get("query") or "",
            "engine": dados.get("engine") or "",
            "results": dados.get("results") or [],
            "sections": dados.get("sections") or [],
            "error": dados.get("error"),
            "notes": list(dados.get("notes") or []),
        }
    if block_type in {"heading", "text", "note", "ai"}:
        return {"type": block_type, "id": block.get("id"), "title": block.get("title"), "text": block.get("text") or ""}
    try:
        blocks, _warnings = _resolve_blocks([block], _source_map(scope))
    except Exception as exc:  # noqa: BLE001 - a fonte pode ter caído
        return {"type": block_type, "id": block.get("id"), "title": block.get("title"), "error": str(exc), "rows": []}
    if not blocks:
        return {
            "type": block_type,
            "id": block.get("id"),
            "title": block.get("title"),
            "error": "Bloco inválido para as fontes atuais.",
            "rows": [],
        }
    try:
        result = _viz().run_query(_block_query(blocks[0]), scope=scope)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Estúdio: consulta do bloco falhou (%s)", exc)
        return {"type": block_type, "id": block.get("id"), "title": block.get("title"), "error": str(exc), "rows": []}
    out = {
        "type": block_type,
        "id": block.get("id"),
        "title": block.get("title"),
        "chart": block.get("chart") or "",
        "width": block.get("width") or 12,
        "dataset": result.get("dataset") or {},
        "dimensions": result.get("dimensions") or [],
        "measures": result.get("measures") or [],
        "columns": result.get("columns") or [],
        "rows": result.get("rows") or [],
        "totals": result.get("totals") or {},
        "error": result.get("error"),
        "notes": (result.get("meta") or {}).get("notes") or [],
    }
    if block_type == "graph":
        out["graph"] = _graph_from(out, max(2, _int(block.get("limit"), 20)))
    return out


def run_report(doc: Dict[str, Any], scope: Optional[Dict[str, Any]] = None, *, block_ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Corre todos os blocos de um relatório (a pré-visualização e o PDF)."""
    wanted = {_text(item, 60) for item in (block_ids or []) if _text(item, 60)}
    mapping = context_vars(doc, scope)
    results: List[Dict[str, Any]] = []
    for block in doc.get("blocks") or []:
        if wanted and str(block.get("id")) not in wanted:
            results.append({"type": block.get("type"), "id": block.get("id"), "title": block.get("title"), "skipped": True})
            continue
        results.append(run_block(block, scope, mapping=mapping))
    problems = [f"{item.get('title') or item.get('id')}: {item['error']}" for item in results if item.get("error")]
    return {
        "report": report_view(doc, include_internal=True),
        "blocks": results,
        "problems": problems,
        "vars": mapping,
        "generated_at": _now(),
    }


# --------------------------------------------------------------------------
# Ficheiros do estúdio
# --------------------------------------------------------------------------
def report_dir(report_id: str) -> Path:
    return STUDIO_DIR / store.safe_filename(report_id, "relatorio")


def store_file(doc: Dict[str, Any], name: str, data: bytes, mime: str = "application/pdf", *, kind: str = PDF_KIND) -> Dict[str, Any]:
    """Guarda um ficheiro do relatório no documento (e no disco)."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("O ficheiro excede o limite de 25 MB.")
    file_id = _new_id("file")
    safe = store.safe_filename(name, "relatorio.pdf")
    target_dir = report_dir(str(doc.get("id") or "relatorio"))
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{file_id}-{safe}"
    path.write_bytes(data)
    item = {
        "id": file_id,
        "name": safe,
        "mime": mime,
        "size": len(data),
        "kind": kind,
        "created_at": _now(),
        "path": str(path),
    }
    doc.setdefault("files", []).insert(0, item)
    del doc["files"][12:]
    return item


def file_of(doc: Dict[str, Any], file_id: str) -> Optional[Tuple[Path, Dict[str, Any]]]:
    item = next((entry for entry in (doc.get("files") or []) if str(entry.get("id")) == str(file_id)), None)
    if item is None:
        return None
    path = Path(str(item.get("path") or ""))
    if not path.exists():
        candidate = report_dir(str(doc.get("id"))) / f"{item.get('id')}-{item.get('name')}"
        if candidate.exists():
            path = candidate
        else:
            return None
    return path, item


def remove_file(doc: Dict[str, Any], file_id: str) -> bool:
    item = next((entry for entry in (doc.get("files") or []) if str(entry.get("id")) == str(file_id)), None)
    if item is None:
        return False
    try:
        path = Path(str(item.get("path") or ""))
        if path.exists():
            path.unlink()
    except OSError as exc:  # pragma: no cover - depende do sistema
        logger.warning("Estúdio: não foi possível apagar %s (%s)", item.get("path"), exc)
    doc["files"].remove(item)
    return True


def drop_file(report_id: str, file_id: str, actor: str = "") -> bool:
    """Remove (e grava) um ficheiro do relatório."""
    with store._lock:  # noqa: SLF001
        data = store.load()
        doc = _doc_in(data, report_id)
        if doc is None:
            raise KeyError(f"Relatório {report_id} não encontrado.")
        if not remove_file(doc, file_id):
            return False
        doc["updated_at"] = _now()
        doc["updated_by"] = actor
        store._write_store(data)  # noqa: SLF001
    return True


def _doc_in(data: Dict[str, Any], report_id: str) -> Optional[Dict[str, Any]]:
    """Relatório dentro de um documento já carregado (uso sob o lock do store)."""
    key = _text(report_id, 80)
    return next((item for item in data.setdefault("studio_reports", []) if str(item.get("id")) == key), None)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def _fmt_number(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—" if value in (None, "") else str(value)
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")


def _fmt_money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—" if value in (None, "") else str(value)
    text = f"{float(value):,.2f}".replace(",", "#").replace(".", ",").replace("#", " ")
    return f"{text} €"


def format_value(value: Any, fmt: str = "") -> str:
    if fmt == "currency":
        return _fmt_money(value)
    if fmt == "percent":
        return f"{_fmt_number(value)} %" if isinstance(value, (int, float)) else "—"
    return _fmt_number(value)


def format_compact(value: Any, fmt: str = "") -> str:
    """Número curto para rótulos de gráficos (`23,7 mM €`, `158 mil`, `898`).

    Os rótulos por cima das barras têm pouco espaço: por extenso, valores de
    milhares de milhões sobrepõem-se ao rótulo do lado. Nos indicadores e nas
    tabelas mantém-se o valor completo.
    """
    if not isinstance(value, (int, float)):
        return "—" if value in (None, "") else str(value)
    number = float(value)
    magnitude = abs(number)
    suffix = " €" if fmt == "currency" else ""
    if magnitude >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}".replace(".", ",") + f" mM{suffix}"
    if magnitude >= 1_000_000:
        return f"{number / 1_000_000:.1f}".replace(".", ",") + f" M{suffix}"
    if magnitude >= 10_000:
        return f"{number / 1_000:.0f} mil{suffix}"
    return format_value(value, fmt)


def _measure_format(block: Dict[str, Any], result: Dict[str, Any]) -> str:
    if block.get("format"):
        return str(block.get("format"))
    measures = result.get("measures") or []
    if measures:
        return str(measures[0].get("format") or "number")
    return "number"


def _bar_drawing(rows: Sequence[Dict[str, Any]], dimension: str, measure: str, *, width: float, height: float,
                 horizontal: bool, fmt: str, labels: Dict[str, str], title: str = "") -> Any:
    """Gráfico de barras desenhado à mão (evita depender de eixos complexos).

    Os rótulos usam a forma compacta (`23,7 mM €`) e são truncados: por extenso,
    um valor de milhares de milhões ficava por cima do rótulo da barra seguinte.
    """
    from reportlab.graphics.shapes import Drawing, Rect, String  # noqa: PLC0415
    from reportlab.lib import colors  # noqa: PLC0415

    brand = colors.HexColor("#0F766E")
    grid = colors.HexColor("#E2E8F0")
    muted = colors.HexColor("#64748B")
    dark = colors.HexColor("#0F172A")
    data = [
        (str(row.get(dimension) or "—"), float(row.get(measure) or 0) if isinstance(row.get(measure), (int, float)) else 0.0)
        for row in rows[:9]
    ]
    drawing = Drawing(width, height)
    if title:
        drawing.add(String(0, height - 9, title, fontName="Helvetica-Bold", fontSize=8.5, fillColor=dark))
    if not data:
        return drawing
    maximum = max(value for _label, value in data) or 1.0
    value_font = 6.5 if horizontal else (5.5 if len(data) > 6 else 6.5)
    row_height = max(8.0, (height - 22) / len(data))
    if horizontal:
        label_width = width * 0.40
        value_width = 52.0
        bar_width = max(20.0, width - label_width - value_width)
        for position, (label, value) in enumerate(data):
            y = height - 22 - (position + 1) * row_height
            drawing.add(String(0, y + row_height / 3, _clip_label(label, 34), fontSize=6.5, fillColor=muted))
            bar = max(1.0, (value / maximum) * bar_width)
            drawing.add(Rect(label_width, y + row_height * 0.22, bar, max(3.0, row_height * 0.56), fillColor=brand, strokeColor=None))
            drawing.add(
                String(label_width + bar + 3, y + row_height / 3, format_compact(value, fmt), fontSize=value_font, fillColor=dark)
            )
    else:
        top = height - 26
        base = 14
        slot = (width - 4) / len(data)
        bar_width = max(4.0, slot * 0.55)
        # Linha de base: dá referência sem eixo desenhado.
        drawing.add(Rect(0, base - 0.4, width, 0.8, fillColor=grid, strokeColor=None))
        for position, (label, value) in enumerate(data):
            bar_height = max(1.0, (value / maximum) * (top - base))
            x = 2 + position * slot + (slot - bar_width) / 2
            drawing.add(Rect(x, base, bar_width, bar_height, fillColor=brand, strokeColor=None))
            drawing.add(String(x + bar_width / 2 - 9, base + bar_height + 2, format_compact(value, fmt), fontSize=value_font, fillColor=dark))
            drawing.add(String(x, base - 9, _clip_label(label, 9), fontSize=6, fillColor=muted))
    if labels:
        drawing.add(String(0, 1, labels.get("origin") or "", fontSize=6, fillColor=muted))
    return drawing


def _clip_label(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _line_drawing(rows: Sequence[Dict[str, Any]], dimension: str, measure: str, *, width: float, height: float, fmt: str) -> Any:
    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, String  # noqa: PLC0415
    from reportlab.lib import colors  # noqa: PLC0415

    brand = colors.HexColor("#0F766E")
    muted = colors.HexColor("#64748B")
    dark = colors.HexColor("#0F172A")
    data = [
        (str(row.get(dimension) or "—"), float(row.get(measure) or 0) if isinstance(row.get(measure), (int, float)) else 0.0)
        for row in rows[:24]
    ]
    drawing = Drawing(width, height)
    if len(data) < 2:
        if data:
            drawing.add(String(0, height / 2, f"{data[0][0]}: {format_value(data[0][1], fmt)}", fontSize=8, fillColor=muted))
        return drawing
    maximum = max(value for _label, value in data) or 1.0
    base, top = 16.0, height - 14.0
    step = (width - 10) / (len(data) - 1)
    points: List[float] = []
    for position, (_label, value) in enumerate(data):
        x = 5 + position * step
        y = base + (value / maximum) * (top - base)
        points.extend([x, y])
    drawing.add(PolyLine(points, strokeColor=brand, strokeWidth=1.2))
    every = max(1, len(data) // 6)
    for position, (label, value) in enumerate(data):
        x = 5 + position * step
        y = base + (value / maximum) * (top - base)
        drawing.add(Circle(x, y, 1.5, fillColor=brand, strokeColor=None))
        if position % every == 0 or position == len(data) - 1:
            drawing.add(String(x - 8, base - 9, _clip_label(label, 10), fontSize=5.5, fillColor=muted))
    # Uma única etiqueta de escala (o pico), em forma compacta.
    drawing.add(String(5, height - 9, f"máx. {format_compact(maximum, fmt)}", fontSize=6, fontName="Helvetica-Bold", fillColor=dark))
    drawing.add(Line(5, base, width - 5, base, strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=0.6))
    return drawing


def _pie_drawing(rows: Sequence[Dict[str, Any]], dimension: str, measure: str, *, width: float, height: float, fmt: str) -> Any:
    """Circular com o **valor e a percentagem na legenda**.

    Os rótulos dentro das fatias colidiam entre si (basta uma fatia pequena) — a
    legenda leva o nome, o valor compacto e o peso de cada fatia.
    """
    from reportlab.graphics.charts.legends import Legend  # noqa: PLC0415
    from reportlab.graphics.charts.piecharts import Pie  # noqa: PLC0415
    from reportlab.graphics.shapes import Drawing, String  # noqa: PLC0415
    from reportlab.lib import colors  # noqa: PLC0415

    palette = ["#0F766E", "#2563EB", "#F59E0B", "#DC2626", "#7C3AED", "#0891B2", "#16A34A", "#DB2777"]
    data = [
        (_clip_label(str(row.get(dimension) or "—"), 26), float(row.get(measure) or 0) if isinstance(row.get(measure), (int, float)) else 0.0)
        for row in rows[:8]
    ]
    drawing = Drawing(width, height)
    data = [(label, value) for label, value in data if value > 0]
    if not data:
        drawing.add(String(0, height / 2, "Sem dados para representar.", fontSize=8, fillColor=colors.HexColor("#64748B")))
        return drawing
    pie = Pie()
    pie.width = min(height * 0.78, width * 0.42)
    pie.height = pie.width
    pie.x = width - pie.width - 6
    pie.y = (height - pie.height) / 2
    pie.data = [value for _label, value in data]
    pie.labels = None
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 0.5
    pie.slices.popout = 0
    total = sum(value for _label, value in data) or 1.0
    for index, (_label, _value) in enumerate(data):
        pie.slices[index].fillColor = colors.HexColor(palette[index % len(palette)])
    legend = Legend()
    legend.x = 2
    legend.y = max(2.0, height - 10 - len(data) * 8.5)
    legend.fontSize = 6.5
    legend.fontName = "Helvetica"
    legend.dxTextSpace = 3
    legend.dy = 8.5
    legend.alignment = "left"
    legend.colorNamePairs = [
        (
            colors.HexColor(palette[index % len(palette)]),
            f"{label} · {format_compact(value, fmt)} ({value / total * 100:.0f} %)",
        )
        for index, (label, value) in enumerate(data)
    ]
    drawing.add(pie)
    drawing.add(legend)
    return drawing


def _graph_drawing(graph: Dict[str, Any], *, width: float, height: float, fmt: str) -> Any:
    """Grafo bipartido simples: origens à esquerda, destinos à direita."""
    from reportlab.graphics.shapes import Circle, Drawing, Line, String  # noqa: PLC0415
    from reportlab.lib import colors  # noqa: PLC0415

    brand = colors.HexColor("#0F766E")
    accent = colors.HexColor("#2563EB")
    muted = colors.HexColor("#64748B")
    drawing = Drawing(width, height)
    edges = list(graph.get("edges") or [])[:10]
    if not edges:
        drawing.add(String(0, height / 2, "Sem relações para representar.", fontSize=8, fillColor=muted))
        return drawing
    origins: List[str] = []
    targets: List[str] = []
    for edge in edges:
        if edge["source"] not in origins:
            origins.append(edge["source"])
        if edge["target"] not in targets:
            targets.append(edge["target"])
    origins, targets = origins[:7], targets[:7]
    maximum = max(float(edge.get("value") or 0) for edge in edges) or 1.0
    top, bottom = height - 12, 10
    def _y(position: int, count: int) -> float:
        if count <= 1:
            return (top + bottom) / 2
        return top - (top - bottom) * (position / (count - 1))
    left_x, right_x = 6.0, width - 6.0
    positions_origin = {name: _y(index, len(origins)) for index, name in enumerate(origins)}
    positions_target = {name: _y(index, len(targets)) for index, name in enumerate(targets)}
    for edge in edges:
        if edge["source"] not in positions_origin or edge["target"] not in positions_target:
            continue
        weight = 0.3 + (float(edge.get("value") or 0) / maximum) * 1.1
        drawing.add(
            Line(
                left_x + 52,
                positions_origin[edge["source"]],
                right_x - 52,
                positions_target[edge["target"]],
                strokeColor=colors.HexColor("#94A3B8"),
                strokeWidth=weight,
            )
        )
    for name, y in positions_origin.items():
        drawing.add(Circle(left_x + 4, y, 2.2, fillColor=brand, strokeColor=None))
        drawing.add(String(left_x + 9, y - 2.5, name[:22], fontSize=6, fillColor=muted))
    for name, y in positions_target.items():
        drawing.add(Circle(right_x - 4, y, 2.2, fillColor=accent, strokeColor=None))
        drawing.add(String(right_x - 58, y - 2.5, name[:22], fontSize=6, fillColor=muted))
    return drawing


def _pdf_sections(doc: Dict[str, Any], results: Sequence[Dict[str, Any]], mapping: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Converte os blocos executados em secções do PDF da casa."""
    sections: List[Dict[str, Any]] = []
    for block, result in zip(doc.get("blocks") or [], results):
        if mapping:
            block = apply_vars(block, mapping)
        block_type = str(block.get("type") or "")
        title = str(block.get("title") or "")
        if result.get("skipped"):
            continue
        if block_type in {"empresa", "web"}:
            # Estes blocos trazem as secções já montadas (texto, tabelas, listas,
            # gráficos): o PDF desenha-as como qualquer outra.
            if result.get("error"):
                sections.append({"kind": "note", "title": title, "text": str(result["error"])})
                continue
            if block_type == "empresa" and result.get("kpis"):
                pairs = [[str(item.get("label") or ""), str(item.get("value") or "—")] for item in result["kpis"]]
                sections.append({"kind": "kpi", "title": f"{title or 'Empresa'} — indicadores", "pairs": pairs, "rows": pairs})
            for sub in result.get("sections") or []:
                sections.append({**sub, "title": sub.get("title") or title})
            continue
        if block_type in {"text", "note", "ai"}:
            text = str(block.get("text") or result.get("text") or "").strip()
            if not text:
                # Bloco ainda sem texto (a IA não correu, por exemplo): não vale a
                # pena imprimir um título com um traço por baixo.
                continue
            sections.append({"kind": block_type, "title": title, "text": text})
            continue
        if block_type == "heading":
            sections.append({"kind": "heading", "title": title, "text": str(block.get("text") or "")})
            continue
        if result.get("error"):
            sections.append({"kind": "note", "title": title, "text": f"Não foi possível calcular esta secção: {result['error']}"})
            continue
        rows = result.get("rows") or []
        fmt = _measure_format(block, result)
        if block_type == "kpi":
            pairs = []
            for measure in result.get("measures") or []:
                value = (result.get("totals") or {}).get(measure.get("id"))
                pairs.append([str(measure.get("label") or measure.get("id")), format_value(value, str(measure.get("format") or fmt))])
            sections.append({"kind": "kpi", "title": title, "pairs": pairs, "rows": pairs})
            continue
        columns = [entry.get("label") or entry.get("key") for entry in (result.get("columns") or [])]
        table_rows = [
            [
                format_value(row.get(entry.get("key")), str(entry.get("format") or ""))
                if entry.get("type") != "dimension"
                else (row.get(entry.get("key")) if row.get(entry.get("key")) is not None else "—")
                for entry in (result.get("columns") or [])
            ]
            for row in rows[:MAX_ROWS]
        ]
        if block_type == "table":
            sections.append({"kind": "table", "title": title, "columns": columns, "rows": table_rows})
            continue
        if block_type == "graph":
            graph = result.get("graph") or {}
            measures = result.get("measures") or []
            value_label = str((measures[0] if measures else {}).get("label") or "Valor")
            # Três colunas em vez de "A → B": a linha cabe numa linha só e lê-se
            # melhor do que uma seta no meio de nomes longos.
            sections.append(
                {
                    "kind": "graph",
                    "title": title,
                    "graph": graph,
                    "columns": ["Origem", "Destino", value_label],
                    "rows": [
                        [str(edge.get("source") or "—"), str(edge.get("target") or "—"), format_value(edge.get("value"), fmt)]
                        for edge in (graph.get("edges") or [])[:15]
                    ],
                }
            )
            continue
        if block_type == "chart":
            chart = str(block.get("chart") or "bar")
            dimension = str((result.get("dimensions") or [{}])[0].get("id") or "")
            measure = str((result.get("measures") or [{}])[0].get("id") or "")
            sections.append(
                {
                    "kind": "chart",
                    "title": title,
                    "chart": chart,
                    "dimension": dimension,
                    "measure": measure,
                    "format": fmt,
                    "rows": rows,
                    "labels": {},
                }
            )
    return sections


def render_pdf(
    doc: Dict[str, Any],
    *,
    scope: Optional[Dict[str, Any]] = None,
    reference: str = "",
    requester: str = "",
) -> Tuple[str, bytes, str]:
    """PDF do relatório (logótipo, gráficos, tabelas e rodapé da plataforma)."""
    try:
        from reportlab.lib import colors  # noqa: PLC0415
        from reportlab.lib.pagesizes import A4  # noqa: PLC0415
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: PLC0415
        from reportlab.lib.units import mm  # noqa: PLC0415
        from reportlab.platypus import (  # noqa: PLC0415
            Image as PdfImage,
            KeepTogether,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - dependência declarada
        raise RuntimeError("reportlab não instalado") from exc

    from api import contribuintes_report as base  # noqa: PLC0415

    brand_color = colors.HexColor("#0F766E")
    dark = colors.HexColor("#0F172A")
    muted = colors.HexColor("#64748B")
    zebra = colors.HexColor("#F1F5F9")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("iq-title", parent=styles["Title"], fontSize=19, leading=22, textColor=dark, alignment=0)
    brand_style = ParagraphStyle("iq-brand", parent=styles["Normal"], fontSize=10, leading=12, textColor=brand_color, fontName="Helvetica-Bold")
    sub_style = ParagraphStyle("iq-sub", parent=styles["Normal"], fontSize=9, leading=12, textColor=muted)
    section_style = ParagraphStyle("iq-section", parent=styles["Normal"], fontSize=12, leading=15, textColor=dark, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=3)
    body_style = ParagraphStyle("iq-body", parent=styles["Normal"], fontSize=9.5, leading=13, textColor=dark)
    note_style = ParagraphStyle("iq-note", parent=body_style, fontSize=8.5, textColor=muted)
    cell_style = ParagraphStyle("iq-cell", parent=styles["Normal"], fontSize=8, leading=11, textColor=dark)
    cell_muted = ParagraphStyle("iq-cell-muted", parent=cell_style, textColor=muted, fontName="Helvetica-Bold")
    kpi_value = ParagraphStyle("iq-kpi", parent=cell_style, fontSize=13, leading=15, fontName="Helvetica-Bold", textColor=brand_color)
    kpi_value_tight = ParagraphStyle("iq-kpi-tight", parent=kpi_value, fontSize=10.5, leading=12)

    def paragraph(value: Any, style: Any = cell_style) -> Paragraph:
        text = str(value if value is not None else "")
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        return Paragraph(escaped or "—", style)

    executed = run_report(doc, scope)
    # Títulos e subtítulos do relatório podem ter variáveis (`{{nome}}`): o que
    # sai impresso é o texto já resolvido.
    display = apply_vars(doc, executed.get("vars") or {})
    sections = _pdf_sections(doc, executed["blocks"], executed.get("vars") or {})
    support = support_email()

    story: List[Any] = []
    logo = base.logo_path()
    header_cells: List[Any] = [Paragraph(str(display.get("title") or "Relatório"), title_style)]
    if logo:
        try:
            picture = PdfImage(str(logo), width=13 * mm, height=13 * mm)
            header_cells = [picture, [Paragraph(str(display.get("title") or "Relatório"), title_style), Paragraph(str(display.get("subtitle") or ""), sub_style)]]
            header = Table([header_cells], colWidths=[16 * mm, None])
            header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
            story.append(header)
        except Exception as exc:  # pragma: no cover
            logger.debug("Logótipo não embutido no PDF do estúdio: %s", exc)
            story.append(paragraph(str(display.get("title") or "Relatório"), title_style))
    else:
        story.append(paragraph(str(display.get("title") or "Relatório"), title_style))
        if display.get("subtitle"):
            story.append(paragraph(str(display["subtitle"]), sub_style))
    # A linha da marca é um bloco à parte: sem espaço, o subtítulo encostava-lhe.
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"{base.BRAND} · {base.BRAND_TAGLINE}", brand_style))
    if support:
        story.append(Spacer(1, 2))
        story.append(Paragraph(f"Apoio: {support}", sub_style))
    if display.get("description"):
        story.append(Spacer(1, 3))
        story.append(paragraph(str(display["description"]), body_style))
    if display.get("summary"):
        story.append(Spacer(1, 4))
        story.append(paragraph(str(display["summary"]), body_style))
    if requester or reference:
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"Referência {reference or '—'} · {requester or '—'}", sub_style))
    story.append(Spacer(1, 8))

    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), brand_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, zebra]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
    )

    for section in sections:
        kind = section["kind"]
        title = section.get("title") or ""
        if title:
            story.append(Paragraph(str(title), section_style))
        if kind == "heading":
            if section.get("text"):
                story.append(paragraph(section["text"], body_style))
            story.append(Spacer(1, 4))
            continue
        if kind in {"text", "ai"}:
            story.append(paragraph(section.get("text") or "", body_style))
            story.append(Spacer(1, 6))
            continue
        if kind == "note":
            story.append(paragraph(section.get("text") or "", note_style))
            story.append(Spacer(1, 6))
            continue
        if kind == "list":
            items = [str(item) for item in (section.get("items") or []) if str(item or "").strip()]
            if not items:
                continue
            for item in items[:10]:
                story.append(paragraph(f"• {item}", body_style))
            story.append(Spacer(1, 6))
            continue
        if kind == "kpi":
            pairs = section.get("pairs") or []
            if not pairs:
                continue
            # Com valores longos (milhares de milhões), o tamanho grande transborda
            # a célula: reduz-se a letra em vez de partir o número.
            longest = max((len(str(value)) for _label, value in pairs), default=0)
            style = kpi_value if longest <= 16 else kpi_value_tight
            data = [
                [paragraph(label, cell_muted) for label, _value in pairs],
                [paragraph(value, style) for _label, value in pairs],
            ]
            table = Table(data, colWidths=[(170 * mm) / max(1, len(pairs))] * len(pairs))
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ECFDF5")),
                        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#99F6E4")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#99F6E4")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(table)
            story.append(Spacer(1, 4))
            continue
        if kind == "chart":
            rows = section.get("rows") or []
            drawing_width = 170 * mm
            chart = section.get("chart")
            try:
                if chart in {"donut", "pie"}:
                    drawing = _pie_drawing(rows, section["dimension"], section["measure"], width=drawing_width, height=44 * mm, fmt=section.get("format") or "number")
                elif chart in {"line", "area"}:
                    drawing = _line_drawing(rows, section["dimension"], section["measure"], width=drawing_width, height=42 * mm, fmt=section.get("format") or "number")
                else:
                    drawing = _bar_drawing(
                        rows,
                        section["dimension"],
                        section["measure"],
                        width=drawing_width,
                        height=44 * mm,
                        horizontal=chart == "bar-h",
                        fmt=section.get("format") or "number",
                        labels=section.get("labels") or {},
                    )
                story.append(KeepTogether(drawing) if len(rows) <= 8 else drawing)
            except Exception as exc:  # noqa: BLE001 - o PDF não pode falhar por um gráfico
                logger.warning("Estúdio: gráfico não desenhado (%s)", exc)
            continue
        if kind in {"table", "graph"}:
            if kind == "graph":
                graph = section.get("graph") or {}
                if graph.get("edges"):
                    try:
                        story.append(_graph_drawing(graph, width=170 * mm, height=48 * mm, fmt="number"))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Estúdio: grafo não desenhado (%s)", exc)
            columns = section.get("columns") or []
            rows = section.get("rows") or []
            if columns and rows:
                data = [[paragraph(column, ParagraphStyle("h", parent=cell_style, textColor=colors.white, fontName="Helvetica-Bold")) for column in columns]]
                data.extend([paragraph(cell) for cell in row] for row in rows[:MAX_ROWS])
                table = Table(data, repeatRows=1)
                table.setStyle(table_style)
                story.append(KeepTogether(table) if len(data) <= 14 else table)
            story.append(Spacer(1, 6))
    if display.get("targets_note"):
        story.append(Spacer(1, 4))
        story.append(paragraph(str(display["targets_note"]), note_style))
    story.append(Spacer(1, 6))
    generated = f"Gerado pelo {base.BRAND} em {datetime.now().strftime('%d/%m/%Y às %H:%M')}."
    story.append(Paragraph(f"{generated}{f' · Apoio: {support}' if support else ''}", sub_style))

    buffer = BytesIO()

    def decorate(canvas: Any, document: Any) -> None:
        canvas.saveState()
        width, _height = document.pagesize
        canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas.setLineWidth(0.5)
        canvas.line(18, 30, width - 18, 30)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        footer = f"{base.BRAND} — {base.BRAND_TAGLINE}"
        if support:
            footer += f" · apoio: {support}"
        canvas.drawString(18, 20, footer)
        canvas.drawRightString(width - 18, 20, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=38,
        title=f"{doc.get('title')} · {base.BRAND}",
        author=base.BRAND,
    )
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    name = f"iq-os-{slug(doc.get('title'), 'relatorio')}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return name, buffer.getvalue(), "application/pdf"


def attach_pdf(report_id: str, actor: str = "", scope: Optional[Dict[str, Any]] = None, *, replace: bool = True) -> Dict[str, Any]:
    """Gera o PDF do relatório e guarda-o no estúdio."""
    with store._lock:  # noqa: SLF001
        data = store.load()
        doc = _doc_in(data, report_id)
        if doc is None:
            raise KeyError(f"Relatório {report_id} não encontrado.")
        name, content, mime = render_pdf(doc, scope=scope)
        if replace:
            for item in list(doc.get("files") or []):
                remove_file(doc, str(item.get("id")))
        item = store_file(doc, name, content, mime)
        doc["updated_at"] = _now()
        doc["updated_by"] = actor
        store._log(data, "studio.report.pdf", actor=actor, detail=f"PDF de «{doc.get('title')}» ({len(content)} bytes)")  # noqa: SLF001
        store._write_store(data)  # noqa: SLF001
        view = report_view(doc, include_internal=True)
    return {"report": view, "file": {key: value for key, value in item.items() if key != "path"}}


def render_for_key(
    key: Any,
    *,
    scope: Optional[Dict[str, Any]] = None,
    reference: str = "",
    requester: str = "",
) -> Optional[Tuple[str, bytes, str]]:
    """PDF de um relatório publicado, a partir da chave `estudio:<id>`.

    É o ponto por onde passam as entregas automáticas (pedido no site e
    encomenda na loja).
    """
    report_id = report_id_from_auto(key)
    if not report_id:
        return None
    doc = get_report(report_id)
    if doc is None:
        raise KeyError(f"Relatório publicado «{report_id}» já não existe.")
    return render_pdf(doc, scope=scope, reference=reference, requester=requester)


# --------------------------------------------------------------------------
# Publicação (site e loja)
# --------------------------------------------------------------------------
def _pricing(payload: Dict[str, Any], current: Dict[str, Any]) -> Tuple[float, float]:
    price = _float(payload.get("price"), _float(current.get("price")))
    list_price = _float(payload.get("list_price"), _float(current.get("list_price")))
    if price < 0 or list_price < 0:
        raise ValueError("O preço não pode ser negativo.")
    if list_price and list_price < price:
        raise ValueError("O preço antigo tem de ser maior do que o preço atual.")
    return price, list_price


def _features(doc: Dict[str, Any]) -> List[str]:
    features: List[str] = []
    for block in doc.get("blocks") or []:
        title = _text(block.get("title"), 200)
        if title and title not in features:
            features.append(title)
    return features[:MAX_FEATURES]


def publish_site(report_id: str, payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Publica o relatório no catálogo da plataforma (o cliente pede e recebe o PDF)."""
    with store._lock:  # noqa: SLF001
        data = store.load()
        doc = _doc_in(data, report_id)
        if doc is None:
            raise KeyError(f"Relatório {report_id} não encontrado.")
        if not (doc.get("blocks") or []):
            raise ValueError("Um relatório sem blocos não pode ser publicado.")
        targets_note = _long_text(payload.get("targets_note"), 400)
        if targets_note:
            doc["targets_note"] = targets_note
        price, list_price = _pricing(payload, (doc.get("publication") or {}).get("site") or {})
        package_id = f"estudio-{store.slug(doc.get('title'), 'relatorio')}"
        package = store.save_package(
            {
                "id": package_id,
                "code": payload.get("code") or "",
                "title": doc.get("title"),
                "subtitle": doc.get("subtitle") or "Relatório da plataforma",
                "note": payload.get("note") or "PDF gerado automaticamente após o pagamento",
                "badge": payload.get("badge") or "NOVO",
                "price": price,
                "list_price": list_price,
                "delivery_days": payload.get("delivery_days") or 1,
                "max_targets": payload.get("max_targets") or 1,
                "active": True,
                "features": _features(doc) or ["Relatório gerado na plataforma"],
                "auto": auto_key(str(doc.get("id"))),
            },
            actor=actor,
        )
        publication = doc.setdefault("publication", _empty_publication())
        publication["site"] = {
            "published": True,
            "package_id": package.get("id") or package_id,
            "price": price,
            "list_price": list_price,
            "at": _now(),
            "by": actor,
        }
        doc["updated_at"] = _now()
        doc["updated_by"] = actor
        store._log(data, "studio.report.published", actor=actor, detail=f"«{doc.get('title')}» no catálogo (preço {price})")  # noqa: SLF001
        store._write_store(data)  # noqa: SLF001
        view = report_view(doc, include_internal=True)
    return {"report": view, "package": package, "target": "site"}


def publish_shop(report_id: str, payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Publica o relatório na loja como produto digital com entrega automática."""
    try:
        from api import shop_store  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - a loja pode não estar disponível
        raise ValueError(f"Loja indisponível: {exc}") from exc

    with store._lock:  # noqa: SLF001
        data = store.load()
        doc = _doc_in(data, report_id)
        if doc is None:
            raise KeyError(f"Relatório {report_id} não encontrado.")
        if not (doc.get("blocks") or []):
            raise ValueError("Um relatório sem blocos não pode ser publicado.")
        targets_note = _long_text(payload.get("targets_note"), 400)
        if targets_note:
            doc["targets_note"] = targets_note
        publication = doc.setdefault("publication", _empty_publication())
        current = publication.get("loja") or {}
        price, list_price = _pricing(payload, current)
        product_id = _text(current.get("product_id"), 80)
        description = _long_text(payload.get("description"), 6000)
        if not description:
            lines = [f"## O que inclui", ""]
            lines.extend(f"- {feature}" for feature in (_features(doc) or ["Relatório gerado na plataforma"]))
            lines.extend(["", "**PDF gerado automaticamente** assim que a encomenda fica paga."])
            description = "\n".join(lines)
        product_payload = {
            "name": doc.get("title"),
            "type": "digital",
            "status": "publicado",
            "short_description": _long_text(payload.get("short_description") or doc.get("subtitle") or doc.get("description"), 240),
            "description": description,
            "price": price,
            "compare_at_price": list_price,
            "tax_rate": payload.get("tax_rate") or store.settings().get("vat_rate") or 23.0,
            "track_stock": False,
            "allow_backorder": True,
            "tags": list(doc.get("tags") or [])[:12],
            "attributes": payload.get("attributes") or [{"label": "Formato", "value": "PDF"}, {"label": "Entrega", "value": "Automática após o pagamento"}],
            "auto_report": auto_key(str(doc.get("id"))),
            "internal_notes": f"Gerado no Estúdio de relatórios ({doc.get('id')}).",
        }
        try:
            if product_id:
                product = shop_store.save_item("products", {**product_payload, "id": product_id}, author=actor)
            else:
                product = shop_store.save_item("products", product_payload, author=actor)
        except KeyError:
            product = shop_store.save_item("products", product_payload, author=actor)
        publication["loja"] = {
            "published": True,
            "product_id": product.get("id"),
            "price": price,
            "list_price": list_price,
            "at": _now(),
            "by": actor,
        }
        doc["updated_at"] = _now()
        doc["updated_by"] = actor
        store._log(data, "studio.report.published", actor=actor, detail=f"«{doc.get('title')}» na loja (preço {price})")  # noqa: SLF001
        store._write_store(data)  # noqa: SLF001
        view = report_view(doc, include_internal=True)
    return {"report": view, "product": product, "target": "loja"}


def publish(report_id: str, payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Publica no canal pedido (`site`, `loja` ou os dois)."""
    target = _text((payload or {}).get("target"), 20).lower() or "site"
    if target == "site":
        return publish_site(report_id, payload or {}, actor)
    if target == "loja":
        return publish_shop(report_id, payload or {}, actor)
    if target == "todos":
        first = publish_site(report_id, payload or {}, actor)
        second = publish_shop(report_id, payload or {}, actor)
        return {"target": "todos", "site": first, "loja": second, "report": second["report"]}
    raise ValueError(f"Canal inválido: {target}. Válidos: site, loja, todos.")


def unpublish(report_id: str, target: str, actor: str = "") -> Dict[str, Any]:
    """Retira o relatório de um canal (o PDF já entregue não é afetado)."""
    key = _text(target, 20).lower()
    if key not in TARGETS:
        raise ValueError(f"Canal inválido: {target}. Válidos: {', '.join(TARGETS)}.")
    with store._lock:  # noqa: SLF001
        data = store.load()
        doc = _doc_in(data, report_id)
        if doc is None:
            raise KeyError(f"Relatório {report_id} não encontrado.")
        publication = doc.setdefault("publication", _empty_publication())
        current = publication.get(key) or {}
        if key == "site" and current.get("package_id"):
            try:
                store.save_package({"id": current["package_id"], "active": False}, actor=actor)
            except ValueError as exc:  # pragma: no cover - pacote removido entretanto
                logger.warning("Estúdio: pacote %s não desativado (%s)", current.get("package_id"), exc)
        if key == "loja" and current.get("product_id"):
            try:
                from api import shop_store  # noqa: PLC0415

                shop_store.set_status("products", str(current["product_id"]), "rascunho", author=actor)
            except Exception as exc:  # noqa: BLE001 - a loja pode estar indisponível
                logger.warning("Estúdio: produto %s não despublicado (%s)", current.get("product_id"), exc)
        publication[key] = {**current, "published": False, "at": _now(), "by": actor}
        doc["updated_at"] = _now()
        doc["updated_by"] = actor
        store._log(data, "studio.report.unpublished", actor=actor, detail=f"«{doc.get('title')}» retirado de {key}")  # noqa: SLF001
        store._write_store(data)  # noqa: SLF001
        view = report_view(doc, include_internal=True)
    return {"report": view, "target": key}


# --------------------------------------------------------------------------
# IA de apoio (com alternativa factual)
# --------------------------------------------------------------------------
_SISTEMA = (
    "És analista de dados da plataforma IQ OS (inteligência financeira em Portugal). "
    "Escreves em português de Portugal, tom profissional e sóbrio, sem markdown decorativo, "
    "sem inventar números e sem referir que és uma IA."
)


def _facts(doc: Dict[str, Any], executed: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo factual dos blocos (é o que a IA recebe e o que fica sem IA)."""
    facts: Dict[str, Any] = {"titulo": doc.get("title"), "subtitulo": doc.get("subtitle") or "", "seccoes": []}
    for block, result in zip(doc.get("blocks") or [], executed.get("blocks") or []):
        item: Dict[str, Any] = {"tipo": block.get("type"), "titulo": block.get("title") or ""}
        if block.get("source"):
            item["fonte"] = (result.get("dataset") or {}).get("label") or block.get("source")
        if result.get("error"):
            item["erro"] = result["error"]
        if block.get("type") == "kpi":
            item["indicadores"] = [
                {"medida": measure.get("label") or measure.get("id"),
                 "valor": (result.get("totals") or {}).get(measure.get("id")),
                 "formato": measure.get("format") or "number"}
                for measure in result.get("measures") or []
            ]
        elif block.get("type") == "empresa":
            ficha = result.get("ficha") or {}
            item.update(
                {
                    "empresa": ficha.get("nome") or ficha.get("empresa"),
                    "nif": ficha.get("nif"),
                    "cae": ficha.get("cae"),
                    "site": ficha.get("site"),
                    "indicadores": [f"{ponto.get('label')}: {ponto.get('value')}" for ponto in (result.get("kpis") or [])],
                    "seccoes": [
                        {
                            "titulo": sub.get("title"),
                            "linhas": (sub.get("rows") or [])[:6] if sub.get("kind") == "table" else [],
                            "pontos": (sub.get("items") or [])[:6],
                            "texto": sub.get("text") or "",
                        }
                        for sub in (result.get("sections") or [])
                    ],
                }
            )
        elif block.get("type") == "web":
            item["pesquisa"] = result.get("query")
            item["sintese"] = result.get("text") or ""
            item["excertos"] = [
                {"titulo": ponto.get("title"), "fonte": ponto.get("href"), "excerto": ponto.get("body")}
                for ponto in (result.get("results") or [])[:5]
            ]
        elif block.get("type") in {"chart", "table", "graph"}:
            rows = result.get("rows") or []
            columns = [entry.get("key") for entry in result.get("columns") or []]
            item["linhas"] = [{key: row.get(key) for key in columns} for row in rows[:12]]
            if block.get("type") == "graph":
                item["relacoes"] = (result.get("graph") or {}).get("edges", [])[:10]
        facts["seccoes"].append(item)
    return facts


def _factual_summary(doc: Dict[str, Any], facts: Dict[str, Any]) -> str:
    parts: List[str] = []
    indicators: List[str] = []
    highlights: List[str] = []
    for section in facts.get("seccoes") or []:
        for indicator in section.get("indicadores") or []:
            indicators.append(f"{indicator['medida']}: {format_value(indicator['valor'], str(indicator.get('formato') or 'number'))}")
        rows = section.get("linhas") or []
        if rows and section.get("titulo"):
            first = rows[0]
            values = [value for key, value in first.items() if isinstance(value, (int, float))]
            label = next((value for value in first.values() if isinstance(value, str)), None)
            if values and label:
                highlights.append(f"{section['titulo']}: «{label}» lidera com {format_value(values[-1], 'number')}")
    if indicators:
        parts.append("Indicadores apurados — " + "; ".join(indicators[:8]) + ".")
    if highlights:
        parts.append("Destaques por secção — " + "; ".join(highlights[:6]) + ".")
    if not parts:
        parts.append("O relatório ainda não tem secções com dados: acrescente indicadores, gráficos ou tabelas para gerar o sumário.")
    return " ".join(parts)


def _factual_insights(result: Dict[str, Any], block: Dict[str, Any]) -> str:
    rows = result.get("rows") or []
    if not rows:
        return "Sem dados nas condições pedidas: confirme os filtros e o período."
    measures = result.get("measures") or []
    dimensions = result.get("dimensions") or []
    if not measures or not dimensions:
        return "Este bloco não tem dimensões ou medidas suficientes para extrair destaques."
    measure = measures[0]
    dimension = dimensions[0]
    values = [
        (str(row.get(dimension.get("id")) or "—"), float(row.get(measure.get("id"))) if isinstance(row.get(measure.get("id")), (int, float)) else 0.0)
        for row in rows
    ]
    total = sum(value for _label, value in values) or 1.0
    ordered = sorted(values, key=lambda item: item[1], reverse=True)
    head = ordered[0]
    tail = ordered[-1]
    top_share = head[1] / total * 100
    lines = [
        f"Maior grupo: {head[0]} com {format_value(head[1], str(measure.get('format') or 'number'))} ({top_share:.0f} % do total).",
        f"Menor grupo: {tail[0]} com {format_value(tail[1], str(measure.get('format') or 'number'))}.",
        f"Grupos analisados: {len(values)}. Total: {format_value(total if total != 1 or sum(v for _l, v in values) else 0, str(measure.get('format') or 'number'))}.",
    ]
    if top_share >= 50:
        lines.append("A concentração é alta: metade ou mais do valor está num só grupo.")
    elif top_share >= 25:
        lines.append("A concentração é moderada — vale a pena olhar para o segundo e terceiro grupos.")
    else:
        lines.append("A distribuição é repartida por vários grupos.")
    return " ".join(lines)


def _suggested_blocks(source_id: str, scope: Optional[Dict[str, Any]] = None, limit: int = 4) -> List[Dict[str, Any]]:
    source_map = _source_map(scope)
    source = source_map.get(source_id or "")
    if not source:
        return []
    suggestions: List[Dict[str, Any]] = []
    for item in source.get("suggestions") or []:
        chart = str(item.get("chart") or "")
        if chart not in CHART_KINDS or chart in {"matrix", "treemap", "scatter", "stacked", "kpi"}:
            continue
        dimensions = [str(value.get("id") if isinstance(value, dict) else value) for value in (item.get("dimensions") or [])]
        measures = [str(value.get("id") if isinstance(value, dict) else value) for value in (item.get("measures") or [])]
        if not dimensions or not measures:
            continue
        suggestions.append(
            _clean_block(
                _block(
                    "chart",
                    str(item.get("title") or f"{dimensions[0]}"),
                    source=source_id,
                    chart=chart,
                    dimensions=dimensions[:1],
                    measures=measures[:1],
                    limit=12,
                )
            )
        )
        if len(suggestions) >= limit:
            return suggestions
    defaults = source.get("defaults") or {}
    dimension = str(defaults.get("dimension") or (source["dimensions"][0]["id"] if source["dimensions"] else ""))
    measure = str(defaults.get("measure") or (source["measures"][0]["id"] if source["measures"] else ""))
    if dimension and measure and len(suggestions) < limit:
        suggestions.append(
            _clean_block(_block("chart", f"{dimension} por {measure}", source=source_id, chart="bar", dimensions=[dimension], measures=[measure], limit=12))
        )
    names = {item["id"] for item in source["measures"]}
    if measure and len(suggestions) < limit:
        indicators = [measure] + (["contagem"] if "contagem" in names and "contagem" != measure else [])
        suggestions.append(_clean_block(_block("kpi", f"Indicadores — {source['label']}", source=source_id, measures=indicators)))
    return suggestions[:limit]


async def assist(payload: Dict[str, Any], session: Any = None) -> Dict[str, Any]:
    """Ajuda da IA: sumário, texto de secção, destaques e sugestões de blocos.

    Nunca falha por falta de modelo: sem IA configurada devolve o texto factual
    montado a partir dos dados (e diz que o fez).
    """
    mode = _text((payload or {}).get("mode"), 20).lower() or "sumario"
    if mode not in AI_MODES:
        raise ValueError(f"Modo de IA inválido: {mode}. Válidos: {', '.join(AI_MODES)}.")
    report_id = _text((payload or {}).get("report"), 80)
    doc = get_report(report_id) if report_id else None
    if report_id and doc is None:
        raise KeyError(f"Relatório {report_id} não encontrado.")
    if doc is None:
        doc = {"title": _text((payload or {}).get("title"), MAX_TITLE) or "Relatório", "blocks": (payload or {}).get("blocks") or []}
        blocks, _warnings = _resolve_blocks(doc["blocks"], _source_map())
        doc["blocks"] = [_clean_block(block) for block in blocks]

    scope = None
    if session is not None:
        user = getattr(session, "user", None)
        scope = {
            "user_id": getattr(user, "id", None),
            "email": getattr(user, "email", None),
            "see_all": str(getattr(user, "role", "member") or "member") == "admin",
        }

    out: Dict[str, Any] = {
        "mode": mode,
        "text": "",
        "blocks": [],
        "factual": "",
        "backend": None,
        "notes": [],
        "warnings": [],
        "generated_at": _now(),
    }

    if mode == "blocos":
        out["blocks"] = _suggested_blocks(_text((payload or {}).get("source"), 80), scope, limit=6)
        out["factual"] = f"{len(out['blocks'])} bloco(s) sugerido(s) a partir da fonte."
        out["text"] = out["factual"]
        return out

    executed = run_report(doc, scope)
    facts = _facts(doc, executed)
    block_id = _text((payload or {}).get("block"), 60)
    target_block = next((block for block in doc.get("blocks") or [] if str(block.get("id")) == block_id), None)
    target_result = None
    if target_block is not None:
        for block, result in zip(doc.get("blocks") or [], executed.get("blocks") or []):
            if str(block.get("id")) == block_id:
                target_result = result
                break

    if mode == "insights":
        factual = _factual_insights(target_result or {}, target_block or {})
    elif mode == "texto":
        factual = _factual_summary(doc, {"seccoes": [s for s in (facts.get("seccoes") or []) if not target_block or s.get("titulo") == target_block.get("title")]} or facts)
    else:
        factual = _factual_summary(doc, facts)
    out["factual"] = factual
    out["text"] = factual

    prompt_extra = _long_text((payload or {}).get("prompt"), MAX_PROMPT)
    instruction = {
        "sumario": "Escreve o sumário executivo do relatório (3 a 5 frases).",
        "texto": "Escreve o texto da secção indicada (2 a 4 frases).",
        "insights": "Escreve os destaques dos dados (3 a 5 pontos corridos, sem listas).",
    }.get(mode, "Escreve o texto pedido.")
    if target_block and target_block.get("title"):
        instruction += f" Secção: «{target_block['title']}»."
    if prompt_extra:
        instruction += f" Pedido do autor: {prompt_extra}"

    backend = None
    try:
        from api import ontology_ai as ai  # noqa: PLC0415
        from api import people_360  # noqa: PLC0415

        backend, note = people_360.resolve_backend(session, (payload or {}).get("backend"))
        if note:
            out["notes"].append(note)
        out["backend"] = {"kind": backend.get("kind"), "provider": backend.get("provider"), "model": backend.get("model")}
        if backend.get("kind") != "cloud":
            out["notes"].append(backend.get("note") or "Sem modelo configurado: texto montado só com os dados.")
            return out
        import json  # noqa: PLC0415

        text = await ai.ask_model(
            backend,
            system=_SISTEMA,
            prompt=instruction + "\n\nDADOS (JSON):\n" + json.dumps(facts, ensure_ascii=False, default=str)[:14000],
            max_tokens=900,
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001 - a IA é uma ajuda, nunca um bloqueio
        out["warnings"].append(f"IA indisponível ({exc}); texto factual.")
        return out
    if not str(text or "").strip():
        out["warnings"].append("A IA devolveu texto vazio; texto factual.")
        return out
    out["text"] = str(text).strip()
    out["mode"] = mode
    out["ai"] = True
    out["notes"].append(
        f"Texto redigido por {backend.get('provider')}:{backend.get('model')} a partir dos dados do relatório."
    )
    return out


# --------------------------------------------------------------------------
# Estado (diagnóstico)
# --------------------------------------------------------------------------
def reset_for_tests() -> None:
    """Só para testes: esquece o catálogo de fontes em cache."""
    _source_cache.clear()
    _ficha_cache.clear()


def state(scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Estado do estúdio: fontes, modelos, relatórios e IA."""
    listing = sources(scope)
    catalog = list_reports(limit=1)
    info: Dict[str, Any] = {
        "module": "reports-studio",
        "sources": len(listing["sources"]),
        "available": listing["available"],
        "templates": len(TEMPLATES),
        "block_types": list(BLOCK_TYPES),
        "chart_types": list(CHART_KINDS),
        "limits": listing["limits"],
        "reports": catalog["stats"],
        "managers": store.report_managers(),
        "problems": listing["problems"],
    }
    try:
        import reportlab  # noqa: PLC0415,F401

        info["pdf"] = True
    except Exception:  # noqa: BLE001
        info["pdf"] = False
    try:
        from api import ontology_ai as ai  # noqa: PLC0415

        info["ai"] = callable(getattr(ai, "ask_model", None))
    except Exception:  # noqa: BLE001
        info["ai"] = False
    return info
