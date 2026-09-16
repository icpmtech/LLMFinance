"""Coletor de marcas do INPI (Portugal) por entidade/titular.

O site https://servicosonline.inpi.pt/pesquisas/main/marcas.jsp expõe um
endpoint ExtJS `POST /pesquisas/Controller` que aceita comandos como:

- PesquisaMarcasEntidade: pesquisa por proprietário/entidade
- DetalheMarca: ficha detalhada de um processo (via nord)
- DetalheMarcaNice: classificação Nice
- DetalheMarcaFases: fases jurídicas
- DetalheEntidades: entidades intervenientes

Mantém intervalos mínimos entre pedidos para não sobrecarregar o INPI.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

INPI_BASE = "https://servicosonline.inpi.pt"
INPI_CONTROLLER = f"{INPI_BASE}/pesquisas/Controller"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": INPI_BASE,
    "Referer": f"{INPI_BASE}/pesquisas/main/marcas.jsp?lang=PT",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

# Evitar flood ao INPI (segundos entre pedidos consecutivos)
MIN_REQUEST_INTERVAL = 0.4

# Campos de data conhecidos no INPI (dd-MM-yyyy)
_INPI_DATE_FIELDS = {
    "dt_apresentacao",
    "dt_pedido",
    "dt_ini_fase_actual",
    "dt_fim_fase_actual",
    "dt_concessao",
    "dt_publicacao",
    "dt_expiracao",
}


@dataclass
class InpiTrademark:
    """Representação normalizada de uma marca devolvida pelo INPI."""

    nord: int
    process_number: str
    mark_name: str
    mark_type: str
    modality: str
    holder_name: str
    application_date: Optional[str] = None
    current_phase: Optional[str] = None
    phase_start_date: Optional[str] = None
    phase_end_date: Optional[str] = None
    nice_classes: List[str] = field(default_factory=list)
    raw_detail: Dict[str, Any] = field(default_factory=dict)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    phases: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    ingested_at: Optional[str] = None
    source_query: Optional[str] = None

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "nord": self.nord,
            "process_number": self.process_number,
            "mark_name": self.mark_name,
            "mark_type": self.mark_type,
            "modality": self.modality,
            "holder_name": self.holder_name,
            "application_date": self.application_date,
            "current_phase": self.current_phase,
            "phase_start_date": self.phase_start_date,
            "phase_end_date": self.phase_end_date,
            "nice_classes": self.nice_classes,
            "entities": self.entities,
            "phases": self.phases,
            "documents": self.documents,
            "ingested_at": self.ingested_at or datetime.utcnow().isoformat(),
            "source_query": self.source_query,
        }
        if include_raw:
            doc["raw_detail"] = self.raw_detail
        return doc


class InpiMarcasClient:
    """Cliente leve para o endpoint ExtJS do INPI."""

    def __init__(
        self,
        base_url: str = INPI_CONTROLLER,
        headers: Optional[Dict[str, str]] = None,
        min_interval: float = MIN_REQUEST_INTERVAL,
    ):
        self.base_url = base_url
        self.headers = {**DEFAULT_HEADERS, **(headers or {})}
        self.min_interval = max(0.0, min_interval)
        self._last_request_at: float = 0.0
        self._session = requests.Session()
        self._session.headers.update(self.headers)

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _post(self, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        self._throttle()
        try:
            resp = self._session.post(self.base_url, data=payload, timeout=timeout)
            resp.raise_for_status()
            # O INPI responde com application/x-json ou text/plain com JSON
            text = resp.text.strip()
            if not text:
                return {"success": False, "error": "resposta vazia"}
            return resp.json()
        except requests.exceptions.RequestException as exc:
            logger.warning("INPI request failed: %s", exc)
            return {"success": False, "error": f"request error: {exc}"}
        except json.JSONDecodeError as exc:
            logger.warning("INPI JSON decode failed: %s", exc)
            return {"success": False, "error": f"json decode: {exc}"}

    def search_by_entity(
        self,
        nome: Optional[str] = None,
        nif: Optional[str] = None,
        codigo: Optional[str] = None,
        morada: Optional[str] = None,
        intervencao: str = "TIT",
        start: int = 0,
        limit: int = 16,
    ) -> Dict[str, Any]:
        """Pesquisa marcas por entidade/proprietário."""
        payload: Dict[str, Any] = {
            "cmd": "PesquisaMarcasEntidade",
            "lang": "PT",
            "codigo": codigo or "",
            "nome": nome or "",
            "morada": morada or "",
            "intervencao": intervencao or "",
            "nif": nif or "",
            "start": start,
            "limit": limit,
        }
        return self._post(payload)

    def get_detail(self, nord: int) -> Dict[str, Any]:
        return self._post({"cmd": "DetalheMarca", "nord": nord})

    def get_nice(self, nord: int) -> Dict[str, Any]:
        return self._post({"cmd": "DetalheMarcaNice", "nord": nord})

    def get_phases(self, nord: int) -> Dict[str, Any]:
        return self._post({"cmd": "DetalheMarcaFases", "nord": nord})

    def get_entities(self, nord: int) -> Dict[str, Any]:
        return self._post({"cmd": "DetalheEntidades", "nord": nord})

    def get_documents(self, nord: int) -> Dict[str, Any]:
        return self._post({"cmd": "DetalheDocumentos", "nord": nord})


def _parse_inpi_date(value: Any) -> Optional[str]:
    """Converte datas INPI (dd-MM-yyyy ou yyyy-MM-dd) para ISO yyyy-MM-dd."""
    if value is None or value == "---" or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    # Tentar formato típico do INPI primeiro
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _norm_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _extract_nice_classes(nice_resp: Dict[str, Any]) -> List[str]:
    classes: List[str] = []
    data = nice_resp if isinstance(nice_resp, dict) else {}
    items = data.get("items") or data.get("data") or []
    if isinstance(items, dict):
        items = [items]
    for item in items or []:
        if not isinstance(item, dict):
            continue
        code = item.get("classe") or item.get("nice") or item.get("codigo") or item.get("class")
        desc = item.get("especificacao") or item.get("descricao") or item.get("description") or ""
        if code:
            classes.append(f"{code}: {desc}".strip(" :"))
    return classes


def _extract_entities(entities_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = entities_resp if isinstance(entities_resp, dict) else {}
    items = data.get("items") or data.get("data") or data.get("enti") or []
    if isinstance(items, dict):
        items = [items]
    result: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = item.get("nome") or item.get("titular") or item.get("designacao") or ""
        nif = item.get("nif") or item.get("nif_entidade") or ""
        role = item.get("intervencao") or item.get("tipo") or "Titular"
        if name:
            result.append({"name": _norm_text(name), "nif": _norm_text(nif), "role": role})
    return result


def _extract_phases(phases_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = phases_resp if isinstance(phases_resp, dict) else {}
    items = data.get("items") or data.get("data") or data.get("fases") or []
    if isinstance(items, dict):
        items = [items]
    result: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        phase = item.get("fase") or item.get("fase_actual") or item.get("descricao") or ""
        start = _parse_inpi_date(item.get("dt_ini") or item.get("dt_inicio") or item.get("dt_ini_fase"))
        end = _parse_inpi_date(item.get("dt_fim") or item.get("dt_fim_fase"))
        if phase:
            result.append({"phase": phase, "start_date": start, "end_date": end})
    return result


def _extract_documents(docs_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = docs_resp if isinstance(docs_resp, dict) else {}
    items = data.get("items") or data.get("data") or []
    if isinstance(items, dict):
        items = [items]
    result: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("nume_doc") or item.get("id") or ""
        doc_type = item.get("tipo") or item.get("tipo_doc") or ""
        url = item.get("url") or ""
        description = item.get("descricao") or item.get("assunto") or ""
        if doc_id or description:
            result.append(
                {
                    "doc_id": _norm_text(doc_id),
                    "type": _norm_text(doc_type),
                    "description": _norm_text(description),
                    "url": _norm_text(url),
                }
            )
    return result


def build_trademark_from_detail(
    search_item: Dict[str, Any],
    detail_resp: Optional[Dict[str, Any]] = None,
    nice_resp: Optional[Dict[str, Any]] = None,
    phases_resp: Optional[Dict[str, Any]] = None,
    entities_resp: Optional[Dict[str, Any]] = None,
    documents_resp: Optional[Dict[str, Any]] = None,
    source_query: Optional[str] = None,
) -> InpiTrademark:
    """Constrói um objeto InpiTrademark normalizado a partir das respostas do INPI."""
    item = search_item if isinstance(search_item, dict) else {}
    nord = item.get("nord") or (detail_resp or {}).get("nord")
    try:
        nord = int(nord)
    except (TypeError, ValueError):
        nord = 0

    detail = detail_resp if isinstance(detail_resp, dict) else {}
    holder = item.get("titular") or detail.get("nome_titular") or detail.get("titular") or ""

    tm = InpiTrademark(
        nord=nord,
        process_number=_norm_text(item.get("nume_proc") or detail.get("nume_proc") or ""),
        mark_name=_norm_text(item.get("sinal") or detail.get("sinal") or ""),
        mark_type=_norm_text(item.get("tipo_sinal") or detail.get("tipo_sinal") or ""),
        modality=_norm_text(item.get("moda") or detail.get("moda") or ""),
        holder_name=_norm_text(holder),
        application_date=_parse_inpi_date(detail.get("dt_pedido") or detail.get("dt_apresentacao")),
        current_phase=_norm_text(detail.get("fase_actual") or ""),
        phase_start_date=_parse_inpi_date(detail.get("dt_ini_fase_actual")),
        phase_end_date=_parse_inpi_date(detail.get("dt_fim_fase_actual")),
        nice_classes=_extract_nice_classes(nice_resp or {}),
        raw_detail=detail,
        entities=_extract_entities(entities_resp or {}),
        phases=_extract_phases(phases_resp or {}),
        documents=_extract_documents(documents_resp or {}),
        source_query=source_query,
    )
    return tm


def search_trademarks_by_entity(
    client: InpiMarcasClient,
    nome: Optional[str] = None,
    nif: Optional[str] = None,
    codigo: Optional[str] = None,
    morada: Optional[str] = None,
    intervencao: str = "TIT",
    include_detail: bool = False,
    max_results: Optional[int] = None,
) -> List[InpiTrademark]:
    """Pesquisa marcas por entidade e opcionalmente carrega detalhes de cada uma."""
    results: List[InpiTrademark] = []
    start = 0
    limit = 16
    total = None
    source_query = nome or nif or codigo or ""

    while True:
        if max_results is not None and len(results) >= max_results:
            break
        resp = client.search_by_entity(
            nome=nome,
            nif=nif,
            codigo=codigo,
            morada=morada,
            intervencao=intervencao,
            start=start,
            limit=limit,
        )
        if not resp.get("success"):
            error = resp.get("error") or "resposta INPI sem success"
            logger.warning("INPI search failed at start=%s: %s", start, error)
            break

        if total is None:
            total = resp.get("totalCount") or resp.get("total") or 0
            try:
                total = int(total)
            except (TypeError, ValueError):
                total = 0

        items = resp.get("items") or []
        if not items:
            break

        for item in items:
            if max_results is not None and len(results) >= max_results:
                break
            nord = item.get("nord")
            if include_detail and nord:
                detail = client.get_detail(nord)
                nice = client.get_nice(nord)
                phases = client.get_phases(nord)
                entities = client.get_entities(nord)
                docs = client.get_documents(nord)
                tm = build_trademark_from_detail(
                    item,
                    detail_resp=detail,
                    nice_resp=nice,
                    phases_resp=phases,
                    entities_resp=entities,
                    documents_resp=docs,
                    source_query=source_query,
                )
            else:
                tm = build_trademark_from_detail(item, source_query=source_query)
            results.append(tm)

        start += limit
        if total and start >= total:
            break

    return results


def fetch_trademarks_for_company(
    company_name: str,
    nif: Optional[str] = None,
    include_detail: bool = True,
    max_results: Optional[int] = None,
    min_interval: float = MIN_REQUEST_INTERVAL,
) -> Dict[str, Any]:
    """API de alto nível: obtém marcas do INPI para uma empresa."""
    client = InpiMarcasClient(min_interval=min_interval)
    results = search_trademarks_by_entity(
        client=client,
        nome=company_name,
        nif=nif or "",
        intervencao="TIT",
        include_detail=include_detail,
        max_results=max_results,
    )
    return {
        "company_name": company_name,
        "nif": nif,
        "total": len(results),
        "trademarks": [tm.to_dict(include_raw=False) for tm in results],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    out = fetch_trademarks_for_company("PRIMAVERA", include_detail=True, max_results=4)
    print(json.dumps(out, ensure_ascii=False, indent=2))
