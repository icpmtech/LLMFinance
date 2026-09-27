"""Mapa OpenStreetMap dos éditos de citação/notificação (CITIUS).

Os éditos **não têm coordenadas**: trazem o **tribunal/serviço** («Entroncamento -
Tribunal Judicial da Comarca de Santarém»). Este módulo converte essa chave numa
posição no mapa, com três níveis de leitura:

| `nivel` | Chave | Significado |
|---|---|---|
| `sede` (omissão) | `tribunal_comarca` | a **terra** onde o processo corre (o primeiro segmento do tribunal) |
| `comarca` | `comarca_judicial` | a **comarca judicial** («… da Comarca de Santarém»), que agrega vários concelhos |
| `tribunal` | `tribunal.keyword` | o serviço completo (ex.: «Lisboa - Tribunal Judicial da Comarca de Lisboa») |

A geocodificação é **offline**, com as tabelas do GeoNames já construídas para o
GLEIF (`data/gleif/geo/pt.json`, ~27 mil localidades): nenhum pedido por édito a
serviços externos. As chaves sem localização conhecida não são inventadas — saem
numa lista própria («sem localização») para o mapa não mentir.

O módulo percorre os documentos (`scan_citacoes`) e agrega em memória: contagem de
éditos, valor das execuções, éditos com documento analisado e o intervalo de datas
de cada local — o que o mapa mostra ao passar/clicar num círculo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.elasticsearch_client import scan_citacoes

logger = logging.getLogger(__name__)

#: Níveis de agregação do mapa (a UI mostra-os como «Sede do tribunal / Comarca / Serviço»).
MAPA_NIVEIS: Dict[str, Dict[str, str]] = {
    "sede": {
        "label": "Sede do tribunal (terra)",
        "campo": "tribunal_comarca",
        "hint": "A terra onde o processo corre — a leitura mais fina do mapa.",
    },
    "comarca": {
        "label": "Comarca judicial",
        "campo": "comarca_judicial",
        "hint": "Agrupa os concelhos da mesma comarca (ex.: «Comarca de Santarém»).",
    },
    "tribunal": {
        "label": "Tribunal/serviço",
        "campo": "tribunal",
        "hint": "O serviço completo, tal como aparece no portal.",
    },
}

#: Teto de documentos analisados por pedido de mapa.
MAPA_MAX_DOCS = 50_000


def mapa_niveis() -> List[Dict[str, str]]:
    """Níveis de agregação disponíveis (chave, rótulo e explicação)."""
    return [{"key": key, **spec} for key, spec in MAPA_NIVEIS.items()]


def _coordinates(place: Optional[str]) -> Optional[Dict[str, float]]:
    """Coordenadas de uma terra portuguesa (tabela offline do GeoNames).

    Aceita o nome da terra («Entroncamento»), a forma «Comarca de X» e a chave
    já limpa («x»). Devolve ``None`` quando não sabe — o chamador põe o local na
    lista de «sem localização» em vez de o colocar no mapa à força.
    """
    if not place:
        return None
    # «Comarca de Santarém» → «Santarém»; «Almada - Tribunal…» → «Almada».
    texto = str(place).split(" - ", 1)[0].strip()
    texto = texto.split(",", 1)[0].strip()
    import re

    texto = re.sub(r"^(comarca|tribunal|ju[íi]zo|minist[ée]rio p[úu]blico)\s+d[aeo]?\s*", "", texto, flags=re.I)
    texto = re.sub(r"^tribunal\s+", "", texto, flags=re.I).strip()
    if not texto:
        return None
    try:
        from api.gleif_geo import resolve

        ponto = resolve("PT", None, texto)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Geocodificação indisponível para «%s»: %s", texto, exc)
        return None
    if not ponto:
        return None
    lat, lon, precisao = ponto
    return {"lat": round(float(lat), 5), "lon": round(float(lon), 5), "precisao": precisao}


def build_citacoes_map(
    *,
    nivel: str = "sede",
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    citado: Optional[str] = None,
    nome: Optional[str] = None,
    papel: Optional[str] = None,
    nif: Optional[str] = None,
    modelo: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    has_texto: Optional[bool] = None,
    max_docs: int = MAPA_MAX_DOCS,
) -> Dict[str, Any]:
    """Constrói os pontos do mapa (por sede, comarca ou serviço) a partir do índice."""
    nivel = nivel if nivel in MAPA_NIVEIS else "sede"
    campo = MAPA_NIVEIS[nivel]["campo"]
    max_docs = max(1, min(int(max_docs) or MAPA_MAX_DOCS, MAPA_MAX_DOCS))

    varredura = scan_citacoes(
        q=q,
        referencia=referencia,
        processo=processo,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        comarca_judicial=comarca_judicial,
        tipo=tipo,
        ato=ato,
        especie=especie,
        citado=citado,
        nome=nome,
        papel=papel,
        nif=nif,
        modelo=modelo,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
        has_texto=has_texto,
        max_docs=max_docs,
    )
    if varredura.get("error"):
        return {"error": varredura["error"], "points": [], "sem_localizacao": []}

    agregado: Dict[str, Dict[str, Any]] = {}
    valor_total = 0.0
    com_texto = 0
    com_documento = 0
    tipos: Dict[str, int] = {}

    for doc in varredura["items"]:
        chave = str(doc.get(campo) or "").strip()
        if not chave:
            chave = "Não especificado"
        ponto = agregado.get(chave)
        if ponto is None:
            ponto = agregado[chave] = {
                "code": chave,
                "label": chave,
                "count": 0,
                "valor": 0.0,
                "com_texto": 0,
                "com_documento": 0,
                "por_tipo": {},
                "min_date": None,
                "max_date": None,
                "top_tribunais": {},
            }
        ponto["count"] += 1
        try:
            valor = float(doc.get("documento_valor") or 0.0)
        except (TypeError, ValueError):
            valor = 0.0
        ponto["valor"] = round(ponto["valor"] + valor, 2)
        valor_total += valor
        if doc.get("has_texto"):
            ponto["com_texto"] += 1
            com_texto += 1
        if doc.get("has_documento"):
            ponto["com_documento"] += 1
            com_documento += 1
        tipo = str(doc.get("tipo") or "Sem tipo")
        ponto["por_tipo"][tipo] = ponto["por_tipo"].get(tipo, 0) + 1
        tipos[tipo] = tipos.get(tipo, 0) + 1
        tribunal_nome = str(doc.get("tribunal") or "").strip()
        if tribunal_nome:
            ponto["top_tribunais"][tribunal_nome] = ponto["top_tribunais"].get(tribunal_nome, 0) + 1
        data = doc.get("data_publicacao")
        if data:
            if not ponto["min_date"] or data < ponto["min_date"]:
                ponto["min_date"] = data
            if not ponto["max_date"] or data > ponto["max_date"]:
                ponto["max_date"] = data

    points: List[Dict[str, Any]] = []
    sem_localizacao: List[Dict[str, Any]] = []
    for chave, ponto in agregado.items():
        coords = _coordinates(chave)
        row = {
            "key": chave,
            "label": chave,
            "count": ponto["count"],
            "valor": ponto["valor"],
            "com_texto": ponto["com_texto"],
            "com_documento": ponto["com_documento"],
            "por_tipo": [
                {"key": k, "count": v}
                for k, v in sorted(ponto["por_tipo"].items(), key=lambda kv: -kv[1])
            ],
            "top_tribunais": [
                {"key": k, "count": v}
                for k, v in sorted(ponto["top_tribunais"].items(), key=lambda kv: -kv[1])[:5]
            ],
            "min_date": ponto["min_date"],
            "max_date": ponto["max_date"],
        }
        if coords:
            points.append({**row, **coords, "nivel": nivel})
        else:
            sem_localizacao.append(row)

    points.sort(key=lambda item: (item["count"], item["valor"]), reverse=True)
    sem_localizacao.sort(key=lambda item: -item["count"])

    return {
        "nivel": nivel,
        "nivel_label": MAPA_NIVEIS[nivel]["label"],
        "niveis": mapa_niveis(),
        "points": points,
        "sem_localizacao": sem_localizacao,
        "totals": {
            "editais": sum(ponto["count"] for ponto in agregado.values()),
            "locais": len(agregado),
            "locais_no_mapa": len(points),
            "locais_sem_coordenadas": len(sem_localizacao),
            "valor": round(valor_total, 2),
            "com_texto": com_texto,
            "com_documento": com_documento,
            "por_tipo": [{"key": k, "count": v} for k, v in sorted(tipos.items(), key=lambda kv: -kv[1])],
            "documents_matching": int(varredura.get("total") or len(varredura["items"])),
            "documents_scanned": len(varredura["items"]),
        },
        "truncated": bool(varredura.get("truncated")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "q": q,
            "tipo": tipo,
            "comarca": comarca_judicial,
            "tribunal": tribunal,
            "papel": papel,
            "nif": nif,
            "data_from": data_from,
            "data_to": data_to,
            "has_texto": has_texto,
        },
    }
