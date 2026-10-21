"""Motor do módulo **DORA** — Digital Operational Resilience Act.

O módulo oferece uma base operacional para a conformidade DORA:

- **Register of Information** consolidado (entidades, funções de negócio,
  sistemas, fornecedores ICT e contratos);
- **Incidentes ICT** com classificação e reporte;
- **Riscos ICT** ligados a ativos e fornecedores;
- **Automations / workflows** para ciclos de conformidade;
- **Relatórios** alinhados com RTS/ITS (Register of Information, incidentes,
  riscos, fornecedores);
- **Conteúdo DORA** recolhido da EIOPA (original + tradução PT) para consulta.

A leitura é pública; a ingestão, cálculo e geração de relatórios exigem sessão
(escrita no módulo `dora`).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api.elasticsearch_client import (
    DORA_CONTEUDO_INDEX,
    DORA_INCIDENTES_INDEX,
    DORA_RECOLHAS_INDEX,
    DORA_REGISTO_INDEX,
    DORA_RELATORIOS_INDEX,
    DORA_RISCOS_INDEX,
    DORA_WORKFLOWS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL_SECONDS = 900

_INDICES_GARANTIDOS = False
_INDICES_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _garantir_indices() -> Optional[Elasticsearch]:
    global _INDICES_GARANTIDOS
    es = get_es_client()
    if not es:
        return None
    if not _INDICES_GARANTIDOS:
        with _INDICES_LOCK:
            if not _INDICES_GARANTIDOS:
                try:
                    ensure_indices(es)
                    _INDICES_GARANTIDOS = True
                except Exception:
                    pass
    return es


def _es_doc(index: str, doc_id: str) -> Optional[Dict[str, Any]]:
    es = _garantir_indices()
    if not es:
        return None
    try:
        return es.get(index=index, id=doc_id).get("_source")
    except Exception:
        return None


def _search_index(
    index: str,
    body: Dict[str, Any],
    q: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    try:
        response = es.search(index=index, body={**body, "size": size, "from": from_})
        hits = response.get("hits", {}).get("hits", [])
        total = response.get("hits", {}).get("total", {})
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        return {"total": total_value, "items": [h.get("_source") for h in hits]}
    except Exception as exc:
        logger.warning("Pesquisa DORA falhou: %s", exc)
        return {"error": f"Elasticsearch: {exc}"}


# ---------------------------------------------------------------------------
# Metadados / conteúdo DORA recolhido da EIOPA
# ---------------------------------------------------------------------------

DORA_CONTENT = {
    "titulo": "Digital Operational Resilience Act (DORA)",
    "fonte": "EIOPA - European Insurance and Occupational Pensions Authority",
    "url": "https://www.eiopa.europa.eu/digital-operational-resilience-act-dora_en",
    "data_extracao": _now(),
    "original": {
        "introducao": (
            "The Digital Operational Resilience Act (DORA) is a regulation introduced by the European Union "
            "to strengthen the digital resilience of financial entities. It entered into application on 17 January 2025 "
            "and ensures that banks, insurance companies, investment firms and other financial entities can withstand, "
            "respond to, and recover from ICT (Information and Communication Technology) disruptions, such as cyberattacks "
            "or system failures. DORA brings harmonisation to rules relating to operational resilience for the financial sector, "
            "applicable to 20 different types of financial entities and ICT third-party service providers."
        ),
        "porque": (
            "The financial sector is increasingly dependent on technology and on tech companies to deliver financial services. "
            "This makes financial entities vulnerable to cyber-attacks or incidents. When not managed properly, ICT risks can lead "
            "to disruptions of financial services offered across borders. This in turn can have an impact on other companies, sectors "
            "and even on the rest of the economy, which underlines the importance of the digital operational resilience of the financial sector. "
            "This is where the Digital Operational Resilience Act, or DORA, comes into play."
        ),
        "pilares": [
            {
                "id": "ict-risk-management",
                "titulo": "ICT risk management",
                "descricao": "Principles and requirements on ICT risk management framework.",
            },
            {
                "id": "ict-third-party-risk",
                "titulo": "ICT third-party risk management",
                "descricao": "Monitoring third-party risk providers and key contractual provisions.",
            },
            {
                "id": "resilience-testing",
                "titulo": "Digital operational resilience testing",
                "descricao": "Basic and advanced testing, including Threat-Led Penetration Testing (TLPT).",
            },
            {
                "id": "ict-incidents",
                "titulo": "ICT-related incidents",
                "descricao": "General requirements and reporting of major ICT-related incidents to competent authorities.",
            },
            {
                "id": "information-sharing",
                "titulo": "Information sharing",
                "descricao": "Exchange of information and intelligence on cyber threats.",
            },
            {
                "id": "oversight-ctpp",
                "titulo": "Oversight of critical third-party providers",
                "descricao": "Oversight framework for critical ICT third-party providers (CTPPs).",
            },
        ],
        "provisoes_legais": {
            "nivel_1": [
                {
                    "titulo": "Regulation (EU) 2022/2554",
                    "url": "https://eur-lex.europa.eu/eli/reg/2022/2554/oj",
                    "descricao": "On digital operational resilience for the financial sector.",
                },
                {
                    "titulo": "Directive (EU) 2022/2556",
                    "url": "https://eur-lex.europa.eu/eli/dir/2022/2556/oj/eng",
                    "descricao": "Amending sectoral directives as regards digital operational resilience.",
                },
            ],
            "nivel_2": [
                {"titulo": "RTS on ICT risk management framework", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1774"},
                {"titulo": "RTS on ICT incidents classification", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1772"},
                {"titulo": "RTS on ICT incidents reporting process", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R0301"},
                {"titulo": "ITS on ICT incidents reporting", "url": "https://eur-lex.europa.eu/eli/reg_impl/2025/302/oj/eng"},
                {"titulo": "RTS on Threat Led Penetration Testing (TLPT)", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R1190"},
                {"titulo": "RTS on ICT third-party policy", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1773"},
                {"titulo": "RTS on subcontracting", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R0532"},
                {"titulo": "ITS on Register of Information", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202402956"},
                {"titulo": "DR on CTPPs designation criteria", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=PI_COM%3AC%282024%29896"},
                {"titulo": "DR on DORA oversight fees", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=PI_COM%3AC%282024%29902"},
                {"titulo": "RTS on harmonisation of oversight conditions", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202500295"},
                {"titulo": "RTS on Joint Examination Team (JET)", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R0420"},
            ],
            "nivel_3": [
                {
                    "titulo": "Guidelines on oversight cooperation",
                    "url": "/publications/joint-guidelines-oversight-cooperation-and-information-exchange-between-esas-and-competent_en",
                },
                {
                    "titulo": "Guidelines on estimation of aggregated annual costs and losses caused by major ICT-related incidents",
                    "url": "https://www.eiopa.europa.eu/document/download/f92c9ae0-889f-45ed-89bc-7123012e0417_en?filename=JC%202024-34_Guidelines%20on%20costs%20and%20losses_DORA.pdf",
                },
            ],
        },
        "oversight": (
            "DORA establishes an EU-wide oversight framework for critical ICT third-party providers (CTPPs) "
            "to ensure that the financial sector remains secure and resilient against ICT disruptions. "
            "The oversight framework helps to address potential systemic and concentration risks arising from "
            "the financial sector's reliance on a limited number of ICT providers."
        ),
    },
    "pt": {
        "introducao": (
            "O Digital Operational Resilience Act (DORA) é um regulamento introduzido pela União Europeia para reforçar "
            "a resiliência digital das entidades financeiras. Entrou em aplicação em 17 de janeiro de 2025 e garante "
            "que bancos, companhias de seguros, empresas de investimento e outras entidades financeiras consigam resistir, "
            "responder e recuperar de perturbações de TIC (Tecnologias de Informação e Comunicação), como ciberataques ou falhas de sistema. "
            "O DORA harmoniza as regras de resiliência operacional para o setor financeiro, aplicando-se a 20 tipos diferentes "
            "de entidades financeiras e de prestadores de serviços de TIC de terceiros."
        ),
        "porque": (
            "O setor financeiro está cada vez mais dependente da tecnologia e das empresas tecnológicas para prestar serviços financeiros. "
            "Isto torna as entidades financeiras vulneráveis a ciberataques ou incidentes. Quando não são geridos corretamente, "
            "os riscos de TIC podem provocar perturbações nos serviços financeiros prestados em diferentes países. "
            "Por sua vez, isto pode afetar outras empresas, setores e até o resto da economia, o que sublinha a importância "
            "da resiliência operacional digital do setor financeiro. É aqui que entra o Digital Operational Resilience Act, ou DORA."
        ),
        "pilares": [
            {
                "id": "ict-risk-management",
                "titulo": "Gestão de riscos de TIC",
                "descricao": "Princípios e requisitos do quadro de gestão de riscos de TIC.",
            },
            {
                "id": "ict-third-party-risk",
                "titulo": "Gestão de riscos de TIC de terceiros",
                "descricao": "Monitorização de prestadores de risco de terceiros e disposições contratuais-chave.",
            },
            {
                "id": "resilience-testing",
                "titulo": "Testes de resiliência operacional digital",
                "descricao": "Testes básicos e avançados, incluindo testes de penetração orientados por ameaças (TLPT).",
            },
            {
                "id": "ict-incidents",
                "titulo": "Incidentes relacionados com TIC",
                "descricao": "Requisitos gerais e reporte de incidentes significativos relacionados com TIC às autoridades competentes.",
            },
            {
                "id": "information-sharing",
                "titulo": "Partilha de informação",
                "descricao": "Troca de informação e inteligência sobre ameaças cibernéticas.",
            },
            {
                "id": "oversight-ctpp",
                "titulo": "Supervisão de prestadores críticos de terceiros",
                "descricao": "Quadro de supervisão dos prestadores críticos de serviços de TIC de terceiros (CTPP).",
            },
        ],
        "provisoes_legais": {
            "nivel_1": [
                {
                    "titulo": "Regulamento (UE) 2022/2554",
                    "url": "https://eur-lex.europa.eu/eli/reg/2022/2554/oj",
                    "descricao": "Sobre a resiliência operacional digital no setor financeiro.",
                },
                {
                    "titulo": "Diretiva (UE) 2022/2556",
                    "url": "https://eur-lex.europa.eu/eli/dir/2022/2556/oj/eng",
                    "descricao": "Altera as diretivas setoriais no que respeita à resiliência operacional digital.",
                },
            ],
            "nivel_2": [
                {"titulo": "RTS sobre quadro de gestão de riscos de TIC", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1774"},
                {"titulo": "RTS sobre classificação de incidentes de TIC", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1772"},
                {"titulo": "RTS sobre processo de reporte de incidentes de TIC", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R0301"},
                {"titulo": "ITS sobre reporte de incidentes de TIC", "url": "https://eur-lex.europa.eu/eli/reg_impl/2025/302/oj/eng"},
                {"titulo": "RTS sobre Threat-Led Penetration Testing (TLPT)", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R1190"},
                {"titulo": "RTS sobre política de terceiros de TIC", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R1773"},
                {"titulo": "RTS sobre subcontratação", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R0532"},
                {"titulo": "ITS sobre Registo de Informação", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202402956"},
                {"titulo": "DR sobre critérios de designação de CTPP", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=PI_COM%3AC%282024%29896"},
                {"titulo": "DR sobre taxas de supervisão do DORA", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=PI_COM%3AC%282024%29902"},
                {"titulo": "RTS sobre harmonização das condições de supervisão", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202500295"},
                {"titulo": "RTS sobre Equipa Conjunta de Exame (JET)", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R0420"},
            ],
            "nivel_3": [
                {
                    "titulo": "Diretrizes sobre cooperação de supervisão",
                    "url": "/publications/joint-guidelines-oversight-cooperation-and-information-exchange-between-esas-and-competent_en",
                },
                {
                    "titulo": "Diretrizes sobre estimativa de custos e prejuízos agregados anuais causados por incidentes significativos relacionados com TIC",
                    "url": "https://www.eiopa.europa.eu/document/download/f92c9ae0-889f-45ed-89bc-7123012e0417_en?filename=JC%202024-34_Guidelines%20on%20costs%20and%20losses_DORA.pdf",
                },
            ],
        },
        "oversight": (
            "O DORA estabelece um quadro de supervisão a nível da UE para os prestadores críticos de serviços de TIC de terceiros (CTPP) "
            "de forma a garantir que o setor financeiro permanece seguro e resiliente face a perturbações de TIC. "
            "O quadro de supervisão ajuda a resolver potenciais riscos sistémicos e de concentração resultantes da dependência "
            "do setor financeiro de um número limitado de prestadores de TIC."
        ),
    },
}


def meta() -> Dict[str, Any]:
    """Metadados e conteúdo original/traduzido da EIOPA."""
    es = _garantir_indices()
    status: Dict[str, Any] = {"indices": {}}
    if es:
        for name in (
            DORA_REGISTO_INDEX,
            DORA_INCIDENTES_INDEX,
            DORA_RISCOS_INDEX,
            DORA_WORKFLOWS_INDEX,
            DORA_RELATORIOS_INDEX,
            DORA_CONTEUDO_INDEX,
            DORA_RECOLHAS_INDEX,
        ):
            try:
                status["indices"][name] = es.indices.stats(index=name).get("indices", {}).get(name, {}).get("total", {}).get("docs", {})
            except Exception:
                status["indices"][name] = {"count": 0}
    return {
        "conteudo": DORA_CONTENT,
        "status": status,
        "modulo": "dora",
        "versao": "1.0.0",
    }


# ---------------------------------------------------------------------------
# Register of Information
# ---------------------------------------------------------------------------


def registo_pesquisa(
    q: Optional[str] = None,
    tipo: Optional[str] = None,
    entidade_id: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    """Pesquisa no Register of Information."""
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    if q:
        query["bool"]["must"].append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["nome^3", "descricao", "tipo", "entidade_nome", "tags"],
                    "operator": "and",
                }
            }
        )
    if tipo:
        query["bool"]["filter"] = [{"term": {"tipo": tipo}}]
    if entidade_id:
        query["bool"]["filter"] = query["bool"].get("filter", []) + [{"term": {"entidade_id": entidade_id}}]
    return _search_index(DORA_REGISTO_INDEX, {"query": query}, q=q, size=size, from_=from_)


def registo_item(tipo: str, item_id: str) -> Optional[Dict[str, Any]]:
    """Devolve um item do Register of Information."""
    return _es_doc(DORA_REGISTO_INDEX, f"{tipo}:{item_id}")


def registo_guardar(user_id: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou atualiza um item do Register of Information."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}

    item = dict(payload)
    tipo = str(item.get("tipo", "outro"))
    item_id = str(item.get("id") or uuid.uuid4())
    item["id"] = item_id
    item["tipo"] = tipo
    item["updated_at"] = _now()
    item.setdefault("created_at", _now())
    item.setdefault("autor_id", user_id)

    doc_id = f"{tipo}:{item_id}"
    try:
        es.index(index=DORA_REGISTO_INDEX, id=doc_id, body=item)
        return {"id": item_id, "tipo": tipo, "ok": True}
    except Exception as exc:
        return {"error": f"Falha ao guardar: {exc}"}


def registo_relacoes(item_id: str, tipo: str) -> Dict[str, Any]:
    """Ligações de um item do registo com outros domínios (fornecedores, sistemas, funções)."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    try:
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"fornecedor_ids": item_id}},
                        {"term": {"sistema_ids": item_id}},
                        {"term": {"funcao_ids": item_id}},
                        {"term": {"entidade_id": item_id}},
                        {"term": {"contrato_ids": item_id}},
                    ]
                }
            }
        }
        res = es.search(index=DORA_REGISTO_INDEX, body=body, size=50)
        return {"total": res["hits"]["total"].get("value", 0), "items": [h["_source"] for h in res["hits"]["hits"]]}
    except Exception as exc:
        return {"error": f"Falha ao obter relações: {exc}"}


# ---------------------------------------------------------------------------
# Incidentes ICT
# ---------------------------------------------------------------------------


def incidentes_pesquisa(
    q: Optional[str] = None,
    severidade: Optional[str] = None,
    estado: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    filters = []
    if q:
        query["bool"]["must"].append(
            {"multi_match": {"query": q, "fields": ["titulo^3", "descricao", "referencia", "sistema", "entidade_nome"], "operator": "and"}}
        )
    if severidade:
        filters.append({"term": {"severidade": severidade}})
    if estado:
        filters.append({"term": {"estado": estado}})
    if filters:
        query["bool"]["filter"] = filters
    return _search_index(DORA_INCIDENTES_INDEX, {"query": query, "sort": [{"data_inicio": {"order": "desc"}}]}, q=q, size=size, from_=from_)


def incidente(id_: str) -> Optional[Dict[str, Any]]:
    return _es_doc(DORA_INCIDENTES_INDEX, id_)


def incidente_guardar(user_id: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    item = dict(payload)
    item_id = str(item.get("id") or uuid.uuid4())
    item["id"] = item_id
    item["updated_at"] = _now()
    item.setdefault("created_at", _now())
    item.setdefault("autor_id", user_id)
    try:
        es.index(index=DORA_INCIDENTES_INDEX, id=item_id, body=item)
        return {"id": item_id, "ok": True}
    except Exception as exc:
        return {"error": f"Falha ao guardar: {exc}"}


# ---------------------------------------------------------------------------
# Riscos ICT
# ---------------------------------------------------------------------------


def riscos_pesquisa(
    q: Optional[str] = None,
    impacto: Optional[str] = None,
    probabilidade: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    filters = []
    if q:
        query["bool"]["must"].append(
            {"multi_match": {"query": q, "fields": ["nome^3", "descricao", "categoria", "ativo", "entidade_nome"], "operator": "and"}}
        )
    if impacto:
        filters.append({"term": {"impacto": impacto}})
    if probabilidade:
        filters.append({"term": {"probabilidade": probabilidade}})
    if filters:
        query["bool"]["filter"] = filters
    return _search_index(DORA_RISCOS_INDEX, {"query": query, "sort": [{"updated_at": {"order": "desc"}}]}, q=q, size=size, from_=from_)


def risco(id_: str) -> Optional[Dict[str, Any]]:
    return _es_doc(DORA_RISCOS_INDEX, id_)


def risco_guardar(user_id: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    item = dict(payload)
    item_id = str(item.get("id") or uuid.uuid4())
    item["id"] = item_id
    item["updated_at"] = _now()
    item.setdefault("created_at", _now())
    item.setdefault("autor_id", user_id)
    try:
        es.index(index=DORA_RISCOS_INDEX, id=item_id, body=item)
        return {"id": item_id, "ok": True}
    except Exception as exc:
        return {"error": f"Falha ao guardar: {exc}"}


# ---------------------------------------------------------------------------
# Workflows / automações
# ---------------------------------------------------------------------------


def workflows_pesquisa(
    q: Optional[str] = None,
    ativo: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    if q:
        query["bool"]["must"].append(
            {"multi_match": {"query": q, "fields": ["nome^3", "descricao", "trigger", "acao"], "operator": "and"}}
        )
    if ativo is not None:
        query["bool"]["filter"] = [{"term": {"ativo": ativo}}]
    return _search_index(DORA_WORKFLOWS_INDEX, {"query": query, "sort": [{"updated_at": {"order": "desc"}}]}, q=q, size=size, from_=from_)


def workflow(id_: str) -> Optional[Dict[str, Any]]:
    return _es_doc(DORA_WORKFLOWS_INDEX, id_)


def workflow_guardar(user_id: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    item = dict(payload)
    item_id = str(item.get("id") or uuid.uuid4())
    item["id"] = item_id
    item["updated_at"] = _now()
    item.setdefault("created_at", _now())
    item.setdefault("autor_id", user_id)
    try:
        es.index(index=DORA_WORKFLOWS_INDEX, id=item_id, body=item)
        return {"id": item_id, "ok": True}
    except Exception as exc:
        return {"error": f"Falha ao guardar: {exc}"}


# ---------------------------------------------------------------------------
# Relatórios ITS/RTS
# ---------------------------------------------------------------------------


def relatorios_pesquisa(
    q: Optional[str] = None,
    tipo: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    filters = []
    if q:
        query["bool"]["must"].append(
            {"multi_match": {"query": q, "fields": ["nome^3", "tipo", "entidade_nome"], "operator": "and"}}
        )
    if tipo:
        filters.append({"term": {"tipo": tipo}})
    if filters:
        query["bool"]["filter"] = filters
    return _search_index(DORA_RELATORIOS_INDEX, {"query": query, "sort": [{"updated_at": {"order": "desc"}}]}, q=q, size=size, from_=from_)


def relatorio(id_: str) -> Optional[Dict[str, Any]]:
    return _es_doc(DORA_RELATORIOS_INDEX, id_)


def relatorio_gerar(user_id: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Gera um relatório ITS/RTS a partir de dados do registo."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}

    tipo = str(payload.get("tipo", "register-of-information"))
    entidade_id = str(payload.get("entidade_id", ""))
    if not entidade_id:
        return {"error": "entidade_id é obrigatório"}

    nome = payload.get("nome") or f"Relatório {tipo} - {entidade_id}"
    try:
        registo_count = es.count(index=DORA_REGISTO_INDEX, body={"query": {"term": {"entidade_id": entidade_id}}})["count"]
        incidentes_count = es.count(index=DORA_INCIDENTES_INDEX, body={"query": {"term": {"entidade_id": entidade_id}}})["count"]
        riscos_count = es.count(index=DORA_RISCOS_INDEX, body={"query": {"term": {"entidade_id": entidade_id}}})["count"]
    except Exception as exc:
        return {"error": f"Falha ao contar dados: {exc}"}

    item = {
        "id": str(uuid.uuid4()),
        "tipo": tipo,
        "nome": nome,
        "entidade_id": entidade_id,
        "autor_id": user_id,
        "resumo": {
            "total_registo": registo_count,
            "total_incidentes": incidentes_count,
            "total_riscos": riscos_count,
        },
        "dados": payload.get("dados", {}),
        "formato": payload.get("formato", "json"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    try:
        es.index(index=DORA_RELATORIOS_INDEX, id=item["id"], body=item)
        return {"id": item["id"], "ok": True, "relatorio": item}
    except Exception as exc:
        return {"error": f"Falha ao guardar relatório: {exc}"}


# ---------------------------------------------------------------------------
# Ingestão de conteúdo e recolhas
# ---------------------------------------------------------------------------


def conteudo_ingestao(user_id: Optional[str]) -> Dict[str, Any]:
    """Indexa o conteúdo DORA recolhido da EIOPA."""
    es = _garantir_indices()
    if not es:
        return {"error": "Elasticsearch indisponível"}

    docs: List[Dict[str, Any]] = []
    base = {
        "fonte": "EIOPA",
        "url": DORA_CONTENT["url"],
        "data_extracao": DORA_CONTENT["data_extracao"],
        "autor_id": user_id,
    }
    # Indexa introdução e "porquê" em ambos os idiomas
    for idioma, chaves in (("pt", ("introducao", "porque", "oversight")), ("en", ("introducao", "porque", "oversight"))):
        for chave in chaves:
            texto = DORA_CONTENT[idioma][chave]
            doc_id = f"{idioma}-{chave}"
            docs.append(
                {
                    "_index": DORA_CONTEUDO_INDEX,
                    "_id": doc_id,
                    "_source": {
                        **base,
                        "idioma": idioma,
                        "tipo": chave,
                        "titulo": DORA_CONTENT["titulo"],
                        "texto": texto,
                    },
                }
            )
    # Indexa pilares
    for idioma in ("pt", "en"):
        for pilar in DORA_CONTENT[idioma]["pilares"]:
            doc_id = f"{idioma}-pilar-{pilar['id']}"
            docs.append(
                {
                    "_index": DORA_CONTEUDO_INDEX,
                    "_id": doc_id,
                    "_source": {
                        **base,
                        "idioma": idioma,
                        "tipo": "pilar",
                        "pilar_id": pilar["id"],
                        "titulo": pilar["titulo"],
                        "texto": f"{pilar['titulo']}. {pilar['descricao']}",
                    },
                }
            )
    # Indexa provisões legais
    for idioma in ("pt", "en"):
        for nivel, itens in DORA_CONTENT[idioma]["provisoes_legais"].items():
            for idx, item in enumerate(itens):
                doc_id = f"{idioma}-provisao-{nivel}-{idx}"
                docs.append(
                    {
                        "_index": DORA_CONTEUDO_INDEX,
                        "_id": doc_id,
                        "_source": {
                            **base,
                            "idioma": idioma,
                            "tipo": "provisao",
                            "nivel": nivel,
                            "titulo": item["titulo"],
                            "url": item["url"],
                            "texto": f"{item['titulo']}. {item.get('descricao', '')}",
                        },
                    }
                )

    try:
        bulk(es, docs)
        es.index(
            index=DORA_RECOLHAS_INDEX,
            id=f"eipa-dora-{DORA_CONTENT['data_extracao']}",
            body={
                "fonte": "EIOPA",
                "url": DORA_CONTENT["url"],
                "data": DORA_CONTENT["data_extracao"],
                "total_docs": len(docs),
                "autor_id": user_id,
            },
        )
        return {"indexados": len(docs), "ok": True}
    except Exception as exc:
        return {"error": f"Falha na ingestão: {exc}"}


def conteudo_pesquisa(q: str, idioma: Optional[str] = None, size: int = 20, from_: int = 0) -> Dict[str, Any]:
    query: Dict[str, Any] = {"bool": {"must": [{"match_all": {}}]}}
    filters = []
    if q:
        query["bool"]["must"] = [
            {"multi_match": {"query": q, "fields": ["titulo^3", "texto", "tipo"], "operator": "and"}}
        ]
    if idioma:
        filters.append({"term": {"idioma": idioma}})
    if filters:
        query["bool"]["filter"] = filters
    return _search_index(DORA_CONTEUDO_INDEX, {"query": query}, q=q, size=size, from_=from_)
