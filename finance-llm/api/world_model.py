"""World Model — o estado do mundo da contratação pública, materializado.

Este módulo transforma os **dados públicos** (lidos por `world_sources.py`) num
modelo de estado com três camadas, gravadas em três índices do Elasticsearch:

1. **Estado** (`finance_world_state`) — um documento por entidade (empresa,
   entidade pública, pessoa), com contagens, valor, atividade, risco e o estado
   derivado («ativo», «inativo», «insolvente»).
2. **Eventos** (`finance_world_events`) — registo temporal append-only:
   adjudicações, contratações, cessações, insolvências e relações criadas. É a
   matéria-prima da linha temporal e da causalidade.
3. **Relações** (`finance_world_relations`) — as arestas do grafo
   (entidade pública → empresa, pessoa → empresa) com peso, valor, datas e
   evidência (os contratos que as sustentam).

O estado é o que alimenta as camadas seguintes: a rede neuronal dinâmica
(`world_neural.py`), o motor de grafo/tempo (`world_graph.py`), o simulador de
futuro (`world_simulator.py`) e o agente de investigação
(`world_investigation.py`).

Modelação (explícita, para não prometer mais do que é)
------------------------------------------------------
- **Risco** é um índice heurístico de 0 a 1, soma ponderada de sinais
  observáveis (insolvência, concentração de valor, dimensão, inatividade,
  dependência de um só cliente). **Não** é um modelo de crédito validado.
- **Atividade** é a frequência relativa de eventos nos últimos 12 meses (da
  amostra), com a tendência calculada contra os 12 meses anteriores.
- As contagens e somas por entidade vêm de **agregações** (exatas para as
  entidades consideradas, com um teto `entity_limit`); as **relações e eventos**
  vêm de uma **amostra** de contratos (`contract_sample`). O mundo é, por isso,
  um modelo representativo e não uma cópia integral dos dados — cada documento
  guarda a versão (`world_version`) e as fontes usadas.

Reconstrução
------------
`rebuild()` corre em segundo plano (ver `world_jobs.py`) e escreve sempre com
um `world_version` novo; os documentos de versões anteriores são apagados
quando a reconstrução é completa (`delete_stale`), para o mundo não acumular
estado obsoleto.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api import world_sources as sources
from api.elasticsearch_client import (
    WORLD_EVENTS_INDEX,
    WORLD_HISTORY_INDEX,
    WORLD_RELATIONS_INDEX,
    WORLD_STATE_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "world"
CONFIG_PATH = DATA_DIR / "config.json"
META_PATH = DATA_DIR / "meta.json"

# ---------------------------------------------------------------------------
# Mermaid: identificadores e rótulos seguros
# ---------------------------------------------------------------------------
# O Mermaid não aceita espaços, acentos nem pontuação num identificador de nó, e
# uma aspa dentro do rótulo fecha-o a meio. Os nomes da plataforma têm tudo isso
# («Administrador da insolvência»), por isso o diagrama era gerado inválido.
_MERMAID_UNSAFE_RE = re.compile(r"[^0-9A-Za-z_]+")


def mermaid_id(value: Any) -> str:
    """Identificador válido para Mermaid: sem acentos, espaços ou pontuação."""
    lowered = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(char for char in lowered if not unicodedata.combining(char))
    safe = _MERMAID_UNSAFE_RE.sub("_", plain).strip("_")
    return safe or "n"


def mermaid_label(value: Any, *, limit: int = 120) -> str:
    """Rótulo válido para Mermaid (aspas, quebras de linha e «&» solto tratados).

    O `<br/>` e o `<small>` usados nos diagramas são HTML a sério e por isso ficam
    como estão; só um `&` que não seja já uma entidade é escapado.
    """
    text = str(value or "").replace('"', "'").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"&(?!(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);)", "&amp;", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or "—"


def mermaid_edge_label(value: Any, *, limit: int = 40) -> str:
    """Rótulo de aresta (`-->|"…"|`) sempre entre aspas.

    Dentro de `|…|` o Mermaid lê `(`, `[` e `{` como início da forma de um nó e
    falha o diagrama inteiro — era o caso de «alvos (anomalias)». Entre aspas o
    texto é opaco; `#`, `|` e `"` passam a entidades para não o fecharem antes
    do tempo.
    """
    text = mermaid_label(value, limit=limit)
    text = text.replace("#", "#35;").replace("|", "#124;").replace('"', "#quot;")
    return f'"{text}"'


class MermaidIds:
    """Identificadores Mermaid únicos, mantendo o id de origem para o mapa."""

    def __init__(self) -> None:
        self._by_source: Dict[str, str] = {}
        self._used: set = set()

    def __call__(self, value: Any) -> str:
        source = str(value or "")
        existing = self._by_source.get(source)
        if existing:
            return existing
        base = mermaid_id(source)
        candidate = base
        index = 2
        while candidate in self._used:
            candidate = f"{base}_{index}"
            index += 1
        self._used.add(candidate)
        self._by_source[source] = candidate
        return candidate

    def __len__(self) -> int:
        return len(self._by_source)

DEFAULT_CONFIG: Dict[str, Any] = {
    # Entidades consideradas por papel/país (teto da agregação `terms`).
    "entity_limit": 2000,
    # Contratos lidos por país para as relações e os eventos (amostra). É esta
    # amostra que define a densidade do grafo: com amostras pequenas, quase todos
    # os pares adjudicante↔adjudicatário aparecem uma só vez e a rede sai esparsa.
    "contract_sample": 8000,
    # Processos de insolvência (CIRE) e cargos (PessoasIQ) na amostra.
    "insolvency_sample": 1500,
    "people_sample": 3000,
    # Ano mínimo dos contratos considerados (None = todos).
    "year_from": None,
    # Limiar do índice de risco: [0, medium[ baixo, [medium, high[ médio,
    # [high, 1] elevado.
    "risk_medium": 0.34,
    "risk_high": 0.62,
    # Apagar o estado de versões anteriores quando a reconstrução é completa.
    "delete_stale": True,
    # Estado temporal: granularidade e janela máxima de períodos por entidade.
    "history_grain": "quarter",
    "history_max_periods": 24,
    # Anos cobertos pela amostra de contratos (estratificada por ano: sem isto o
    # histórico teria um só período com atividade).
    "contract_years": 12,
    # Agendamento (cron) da reconstrução do mundo e do ciclo da rede.
    "schedule_enabled": False,
    "schedule_cron": "0 4 * * *",
    "schedule_timezone": "Europe/Lisbon",
    "schedule_train_network": True,
    # **Fontes do sistema associadas ao Public Data** (ids de
    # `world_sources.SOURCES`): a reconstrução só lê o que está associado, e o
    # grafo do pipeline mostra exatamente estas fontes.
    "sources": list(sources.DEFAULT_SOURCE_IDS),
    # Registos lidos por cada fonte adicional (registo, menções, publicações).
    "source_sample": 20000,
}

#: Rótulos dos eventos (para a UI e os relatórios).
#:
#: Taxonomia **suportada pelos dados disponíveis** (não se inventam tipos que a
#: fonte não permite distinguir):
#:
#: - `adjudicacao` / `contratacao` — das adjudicações dos contratos (PT e ES);
#: - `cessacao` — contratos com fim declarado (`tipoFimContrato` + data de fecho);
#: - `atraso` — fecho declarado **depois** do prazo (`prazoExecucao`);
#: - `insolvencia` — intervenientes dos processos do CIRE;
#: - `cargo_iniciado` — cargos anunciados nas publicações societárias;
#: - `publicacao_societaria` — actos publicados no MJ (constituição, alterações);
#: - `marca_registada` — marcas registadas (INPI) por NIF;
#: - `mencao` — menções externas (redes sociais/imprensa) ligadas por NIF ou nome;
#: - `relacao_criada` — criação de uma aresta no grafo.
EVENT_LABELS = {
    "adjudicacao": "Adjudicação recebida",
    "contratacao": "Contrato adjudicado",
    "cessacao": "Contrato cessado",
    "atraso": "Atraso na execução",
    "insolvencia": "Processo de insolvência",
    "cargo_iniciado": "Cargo anunciado",
    "publicacao_societaria": "Publicação societária",
    "marca_registada": "Marca registada",
    "mencao": "Menção externa",
    "relacao_criada": "Relação criada",
    "primeiro_contrato": "Primeiro contrato",
}

#: Rótulos das relações.
RELATION_LABELS = {
    "adjudicou": "Adjudicou a",
    "cargo_em": "Cargo em",
}

_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Configuração e metadados
# ---------------------------------------------------------------------------
def load_config() -> Dict[str, Any]:
    """Configuração do módulo (`data/world/config.json`), com os valores por omissão."""
    config = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                config.update({k: v for k, v in stored.items() if v is not None or k == "year_from"})
    except Exception as exc:
        logger.warning("Configuração do World Model ilegível (%s): %s", CONFIG_PATH, exc)
    return config


def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda (parcialmente) a configuração do módulo."""
    with _lock:
        config = load_config()
        for key, value in (patch or {}).items():
            if key in DEFAULT_CONFIG:
                config[key] = value
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config


def _load_meta() -> Dict[str, Any]:
    try:
        if META_PATH.exists():
            stored = json.loads(META_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                return stored
    except Exception:
        pass
    return {}


def _save_meta(patch: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        meta = _load_meta()
        meta.update(patch or {})
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta


def meta() -> Dict[str, Any]:
    """Metadados do módulo: índices, fontes públicas, eventos, parâmetros e último rebuild."""
    config = load_config()
    saved = _load_meta()
    return {
        "module": "world",
        "label": "World Model",
        "indexes": {
            "state": WORLD_STATE_INDEX,
            "events": WORLD_EVENTS_INDEX,
            "relations": WORLD_RELATIONS_INDEX,
            "history": WORLD_HISTORY_INDEX,
        },
        "sources": sources.SOURCES,
        "event_kinds": [{"id": k, "label": v} for k, v in EVENT_LABELS.items()],
        "relation_kinds": [{"id": k, "label": v} for k, v in RELATION_LABELS.items()],
        "config": config,
        "last_rebuild": saved.get("last_rebuild"),
        "version": saved.get("version"),
        "architecture": ARCHITECTURE,
    }


#: Descrição do pipeline (a mesma do diagrama) — servida ao frontend.
ARCHITECTURE: List[Dict[str, Any]] = [
    {
        "id": "public-data",
        "label": "Public Data",
        "hint": "Contratos públicos, empresas, entidades públicas e pessoas",
        "items": [
            "Contratos Públicos (PT/ES)",
            "Empresas",
            "Entidades Públicas",
            "Pessoas e cargos",
            "CAE / Classificações (CPV)",
            "Valores",
            "Datas",
            "Adjudicações",
            "Execução / Alterações",
        ],
        "backend": "world_sources.py",
    },
    {
        "id": "world-model",
        "label": "World Model",
        "hint": "Estado materializado: entidades, contratos, relações, eventos e histórico",
        "items": [
            "Estado da empresa",
            "Estado dos contratos",
            "Estado das entidades",
            "Estado das pessoas",
            "Relações",
            "Eventos",
            "Histórico temporal",
        ],
        "backend": "world_model.py",
    },
    {
        "id": "dynamic-network",
        "label": "Dynamic Neural Network",
        "hint": "Crescimento, poda, memória e previsão sobre o estado do mundo",
        "items": ["Growth", "Pruning", "Memory", "Prediction"],
        "backend": "world_neural.py",
    },
    {
        "id": "graph-temporal",
        "label": "Graph / Temporal Engine",
        "hint": "Relações, eventos, timestamps e causalidade",
        "items": ["Relações", "Eventos", "Timestamps", "Causalidade"],
        "backend": "world_graph.py",
    },
    {
        "id": "future-simulator",
        "label": "Future Simulator",
        "hint": "t0 → t1 → t2 → t3: novos contratos, atrasos, cancelamentos, risco",
        "items": [
            "Novos contratos",
            "Atrasos",
            "Cancelamentos",
            "Novas relações",
            "Alterações financeiras",
            "Mudança de risco",
        ],
        "backend": "world_simulator.py",
    },
    {
        "id": "investigation-agent",
        "label": "Investigation Agent",
        "hint": "Observe → Hypothesize → Search → Validate → Simulate → Evidence Report",
        "items": ["Observe", "Hypothesize", "Search", "Validate", "Simulate", "Evidence Report"],
        "backend": "world_investigation.py",
    },
]


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def _ref_for(nif: str) -> str:
    """Referência estável de uma entidade (independente do papel que aí apareça)."""
    return f"entidade:{nif}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _risk_label(value: float, config: Dict[str, Any]) -> str:
    if value >= float(config.get("risk_high", 0.62)):
        return "elevado"
    if value >= float(config.get("risk_medium", 0.34)):
        return "médio"
    return "baixo"


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _clean_text(value: Any) -> Optional[str]:
    """Texto simples e limpo (para campos descritivos curtos, ex.: papéis)."""
    if value is None:
        return None
    text = " ".join(str(value).replace("\xa0", " ").split())
    return text[:120] or None


def _period_of(ts: str, grain: str = "quarter") -> Optional[Tuple[str, str, str]]:
    """Converte uma data ISO no período (`grain`) a que pertence.

    Devolve `(chave, início, fim)`: `("2026-Q3", "2026-07-01", "2026-09-30")`.
    As chaves são ordenáveis alfabeticamente **de propósito** (`2026-Q3`), para se
    poder juntar histórico e ordenar no Elasticsearch sem scripts.
    """
    if not ts or len(str(ts)) < 7:
        return None
    try:
        day = datetime.fromisoformat(str(ts)[:10])
    except ValueError:
        return None
    year = day.year
    if grain == "year":
        return (f"{year}", f"{year}-01-01", f"{year}-12-31")
    if grain == "month":
        last = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return (f"{year}-{day.month:02d}", f"{year}-{day.month:02d}-01", last.strftime("%Y-%m-%d"))
    quarter = (day.month - 1) // 3 + 1
    month = (quarter - 1) * 3 + 1
    end_month = month + 2
    # Último dia do **trimestre** (mês final), nunca do mês de início: somar os
    # dias ao mês de início dava fins de período errados (2026-Q3 terminava a
    # 2026-08-31), o que corrompia a concentração e a inatividade do histórico.
    last_day = (datetime(year, end_month, 1).replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return (f"{year}-Q{quarter}", f"{year}-{month:02d}-01", last_day.strftime("%Y-%m-%d"))


def risk_score(
    *,
    insolvent: bool,
    insolvency_roles: Optional[Iterable[str]],
    contracts: int,
    value: float,
    concentration: float,
    inactive_years: float,
    config: Optional[Dict[str, Any]] = None,
) -> float:
    """Índice de risco (0–1) — heurística documentada, usada pelo estado **e** pelo histórico.

    É a mesma função nos dois sítios de propósito: o risco de cada período tem de
    ser comparável com o risco atual (se mudasse de fórmula, a série não seria
    legível).
    """
    config = config or DEFAULT_CONFIG
    risk = 0.0
    risk += 0.45 if insolvent else 0.0
    if not insolvent and insolvency_roles:
        risk += 0.12
    risk += 0.20 * _clip(concentration)
    risk += 0.10 * min(1.0, contracts / 25.0)
    risk += 0.10 * _log_scale(value, 8.5)
    risk += 0.13 * min(1.0, max(0.0, inactive_years) / 4.0)
    return round(_clip(risk), 4)


def _log_scale(value: Optional[float], ceiling: float = 8.0) -> float:
    """Escala logarítmica estável em [0,1] (valor monetário → sinal de risco)."""
    if not value or value <= 0:
        return 0.0
    return _clip(math.log10(value + 10.0) / ceiling)


def _fmt_int(value: Any) -> str:
    """Inteiro com separador de milhares ("41 809") — igual ao do frontend."""
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _fmt_money(value: Any) -> str:
    """Valor em euros legível para relatórios Markdown/Mermaid."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.2f} €".replace(",", " ")


def months_between(first: Optional[str], last: Optional[str]) -> Optional[int]:
    """Meses entre duas datas ISO (inteiro, mínimo 0)."""
    if not first or not last:
        return None
    try:
        a = datetime.fromisoformat(first[:10])
        b = datetime.fromisoformat(last[:10])
    except Exception:
        return None
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


# ---------------------------------------------------------------------------
# Construção do mundo
# ---------------------------------------------------------------------------
class _EntityStore:
    """Acumulador de entidades durante a reconstrução do mundo."""

    def __init__(self) -> None:
        self.entities: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.relations: Dict[str, Dict[str, Any]] = {}
        self._event_ids: set = set()

    # -- entidades ---------------------------------------------------------
    def touch(
        self,
        nif: str,
        name: Optional[str],
        role: str,
        country: str,
        source: str,
        entity_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        nif = str(nif or "").strip()
        if not nif:
            return {}
        ref = _ref_for(nif)
        entity = self.entities.get(ref)
        if entity is None:
            entity = {
                "entity_ref": ref,
                "entity_id": nif,
                "entity_type": entity_type or "empresa",
                "name": name,
                "names": [],
                "country": country,
                "roles": [],
                "sources": [],
                "contracts_count": 0,
                "contracts_value": 0.0,
                "counterparties": set(),
                "cpv": {},
                "first_seen": None,
                "last_event_at": None,
                "insolvent": False,
                "insolvency_roles": [],
                "dependency": 0.0,
            }
            self.entities[ref] = entity
        if entity_type and entity.get("entity_type") in (None, "empresa") and entity_type != "empresa":
            entity["entity_type"] = entity_type
        if role and role not in entity["roles"]:
            entity["roles"].append(role)
        if source and source not in entity["sources"]:
            entity["sources"].append(source)
        if name:
            if not entity.get("name"):
                entity["name"] = name
            if name not in entity["names"]:
                entity["names"].append(name)
        if country and not entity.get("country"):
            entity["country"] = country
        return entity

    def add_contract_metrics(self, nif: str, contracts: int, value: Optional[float], first: Optional[str], last: Optional[str]) -> None:
        entity = self.touch(nif, None, "", "Portugal", "contratos")
        if not entity:
            return
        entity["contracts_count"] = max(int(entity.get("contracts_count") or 0), int(contracts or 0))
        entity["contracts_value"] = max(float(entity.get("contracts_value") or 0.0), float(value or 0.0))
        if first and (not entity.get("first_seen") or first < entity["first_seen"]):
            entity["first_seen"] = first
        if last and (not entity.get("last_event_at") or last > entity["last_event_at"]):
            entity["last_event_at"] = last

    def add_sample_metrics(self, nif: str, value: Optional[float], ts: Optional[str]) -> None:
        """Acumula contratos e valor vistos na **amostra** para uma entidade.

        As agregações só cobrem as maiores entidades (`entity_limit`). Sem este
        acumulador, as entidades que só aparecem na amostra ficariam com zero
        contratos e zero euros — o que estragaria o estado, o risco e as
        features da rede.
        """
        entity = self.entities.get(_ref_for(nif))
        if entity is None:
            return
        entity["sample_contracts"] = int(entity.get("sample_contracts") or 0) + 1
        entity["sample_value"] = float(entity.get("sample_value") or 0.0) + float(value or 0.0)
        if ts:
            if not entity.get("first_seen") or ts < entity["first_seen"]:
                entity["first_seen"] = ts
            if not entity.get("last_event_at") or ts > entity["last_event_at"]:
                entity["last_event_at"] = ts

    # -- eventos -----------------------------------------------------------
    def add_event(self, event: Dict[str, Any]) -> None:
        key = "|".join(
            str(event.get(part) or "")
            for part in ("kind", "entity_ref", "ts", "counterparty_ref", "source_id")
        )
        if key in self._event_ids:
            return
        self._event_ids.add(key)
        self.events.append(event)

    # -- relações ----------------------------------------------------------
    def add_relation(
        self,
        kind: str,
        source_ref: str,
        source_name: Optional[str],
        source_type: str,
        target_ref: str,
        target_name: Optional[str],
        target_type: str,
        ts: Optional[str],
        value: Optional[float],
        evidence: Optional[str] = None,
        country: Optional[str] = None,
    ) -> None:
        if not source_ref or not target_ref or source_ref == target_ref:
            return
        relation_id = f"{kind}:{source_ref}>{target_ref}"
        relation = self.relations.get(relation_id)
        if relation is None:
            relation = {
                "relation_id": relation_id,
                "kind": kind,
                "source_ref": source_ref,
                "source_name": source_name,
                "source_type": source_type,
                "target_ref": target_ref,
                "target_name": target_name,
                "target_type": target_type,
                "contracts_count": 0,
                "value_sum": 0.0,
                "first_ts": ts,
                "last_ts": ts,
                "evidence": [],
                "country": country,
            }
            self.relations[relation_id] = relation
        relation["contracts_count"] = int(relation.get("contracts_count") or 0) + 1
        relation["value_sum"] = float(relation.get("value_sum") or 0.0) + float(value or 0.0)
        if ts:
            if not relation.get("first_ts") or ts < relation["first_ts"]:
                relation["first_ts"] = ts
            if not relation.get("last_ts") or ts > relation["last_ts"]:
                relation["last_ts"] = ts
        if not relation.get("source_name") and source_name:
            relation["source_name"] = source_name
        if not relation.get("target_name") and target_name:
            relation["target_name"] = target_name
        if evidence:
            kept = relation["evidence"]
            if evidence not in kept and len(kept) < 12:
                kept.append(evidence)


def _event_severity(value: Optional[float]) -> float:
    """Severidade de um evento por valor (escala log, 0–1)."""
    return round(_log_scale(value, 8.0), 4)


def _entity_type_for_roles(roles: Iterable[str]) -> str:
    roles = set(roles or [])
    if "adjudicatario" in roles:
        return "empresa"
    if "adjudicante" in roles:
        return "entidade_publica"
    if "insolvente" in roles or "credor" in roles:
        return "empresa"
    if "cargo" in roles:
        return "pessoa"
    return "outro"


def _collect_from_source_metrics(store: _EntityStore, records: List[Dict[str, Any]], role: str, entity_type: str, source_id: str) -> None:
    for record in records:
        nif = str(record.get("nif") or "").strip()
        if not nif:
            continue
        store.touch(nif, record.get("name"), role, record.get("country") or "Portugal", source_id, entity_type)
        store.add_contract_metrics(nif, record.get("contracts") or 0, record.get("value"), record.get("first"), record.get("last"))


def _collect_from_contracts(store: _EntityStore, contracts: List[Dict[str, Any]], version: int) -> None:
    """Gera eventos e relações a partir da amostra de contratos."""
    for contract in contracts:
        country = contract.get("country") or "Portugal"
        source_id = contract.get("uid")
        ts = contract.get("date")
        value = contract.get("value")
        cpvs = contract.get("cpv") or []
        buyers = contract.get("adjudicantes") or []
        winners = contract.get("adjudicatarios") or []
        severity = _event_severity(value)

        for winner in winners:
            store.touch(winner["nif"], winner.get("name"), "adjudicatario", country, contract.get("source") or "contratos", "empresa")
            store.add_sample_metrics(winner["nif"], value, ts)
        for buyer in buyers:
            store.touch(buyer["nif"], buyer.get("name"), "adjudicante", country, contract.get("source") or "contratos", "entidade_publica")
            store.add_sample_metrics(buyer["nif"], value, ts)

        # Eventos: uma adjudicação (do lado da empresa) e uma contratação (do
        # lado de quem contrata), para que os dois lados tenham linha temporal.
        for winner in winners[:4]:
            ref = _ref_for(winner["nif"])
            entity = store.entities.get(ref) or {}
            entity.setdefault("cpv", {})
            for cpv in cpvs[:3]:
                code = cpv.get("code")
                if code:
                    entity["cpv"][code] = entity["cpv"].get(code, 0) + 1
            store.add_event(
                {
                    "kind": "adjudicacao",
                    "entity_ref": ref,
                    "entity_type": entity.get("entity_type"),
                    "entity_id": winner["nif"],
                    "entity_name": winner.get("name"),
                    "counterparty_ref": _ref_for(buyers[0]["nif"]) if buyers else None,
                    "counterparty_name": buyers[0].get("name") if buyers else None,
                    "ts": ts,
                    "value": value,
                    "severity": severity,
                    "country": country,
                    "source_index": contract.get("index"),
                    "source_id": source_id,
                    "object": contract.get("object"),
                    "cpv": [c.get("code") for c in cpvs[:3]],
                }
            )
            if entity:
                if buyers:
                    entity["counterparties"].add(_ref_for(buyers[0]["nif"]))
        for buyer in buyers[:2]:
            ref = _ref_for(buyer["nif"])
            entity = store.entities.get(ref) or {}
            store.add_event(
                {
                    "kind": "contratacao",
                    "entity_ref": ref,
                    "entity_type": entity.get("entity_type"),
                    "entity_id": buyer["nif"],
                    "entity_name": buyer.get("name"),
                    "counterparty_ref": _ref_for(winners[0]["nif"]) if winners else None,
                    "counterparty_name": winners[0].get("name") if winners else None,
                    "ts": ts,
                    "value": value,
                    "severity": severity,
                    "country": country,
                    "source_index": contract.get("index"),
                    "source_id": source_id,
                }
            )

        # Cessação: contrato com fim declarado.
        if contract.get("end_date") and (contract.get("end_type") or "").strip():
            for winner in winners[:2]:
                store.add_event(
                    {
                        "kind": "cessacao",
                        "entity_ref": _ref_for(winner["nif"]),
                        "entity_type": "empresa",
                        "entity_id": winner["nif"],
                        "entity_name": winner.get("name"),
                        "ts": contract.get("end_date"),
                        "value": value,
                        "severity": _clip(severity + 0.2),
                        "country": country,
                        "source_index": contract.get("index"),
                        "source_id": source_id,
                        "reason": contract.get("end_type"),
                    }
                )

        # Atraso: o contrato fechou depois do prazo de execução previsto
        # (data de celebração + `prazoExecucao`). É o único sinal de execução que
        # os dados públicos permitem calcular sem inferência.
        end_date = contract.get("end_date")
        expected_end = contract.get("expected_end")
        if end_date and expected_end and str(end_date) > str(expected_end):
            try:
                delay_days = (
                    datetime.fromisoformat(str(end_date)[:10]) - datetime.fromisoformat(str(expected_end)[:10])
                ).days
            except ValueError:
                delay_days = 0
            if delay_days > 30:
                for winner in winners[:2]:
                    store.add_event(
                        {
                            "kind": "atraso",
                            "entity_ref": _ref_for(winner["nif"]),
                            "entity_type": "empresa",
                            "entity_id": winner["nif"],
                            "entity_name": winner.get("name"),
                            "ts": end_date,
                            "value": value,
                            "severity": _clip(0.25 + min(1.0, delay_days / 730.0)),
                            "country": country,
                            "source_index": contract.get("index"),
                            "source_id": source_id,
                            "delay_days": delay_days,
                            "expected_end": expected_end,
                        }
                    )

        # Relações: cada par adjudicante↔adjudicatário.
        for buyer in buyers[:2]:
            for winner in winners[:4]:
                store.add_relation(
                    kind="adjudicou",
                    source_ref=_ref_for(buyer["nif"]),
                    source_name=buyer.get("name"),
                    source_type="entidade_publica",
                    target_ref=_ref_for(winner["nif"]),
                    target_name=winner.get("name"),
                    target_type="empresa",
                    ts=ts,
                    value=value,
                    evidence=source_id,
                    country=country,
                )
                if winners:
                    counterparty_ref = _ref_for(buyer["nif"])
                    entity = store.entities.get(_ref_for(winner["nif"]))
                    if entity is not None:
                        entity["counterparties"].add(counterparty_ref)


def _collect_insolvencies(store: _EntityStore, records: List[Dict[str, Any]]) -> None:
    for record in records:
        nif = str(record.get("nif") or "").strip()
        if not nif:
            continue
        role = (record.get("role") or "").lower()
        insolvent = "insolvente" in role or not role
        store.touch(
            nif,
            record.get("name"),
            "insolvente" if insolvent else (role or "credor"),
            "Portugal",
            "cire",
            "empresa",
        )
        entity = store.entities.get(_ref_for(nif))
        if entity is not None:
            if insolvent:
                entity["insolvent"] = True
                entity["insolvency_roles"].append("insolvente")
            elif role:
                entity["insolvency_roles"].append(role)
        store.add_event(
            {
                "kind": "insolvencia",
                "entity_ref": _ref_for(nif),
                "entity_type": "empresa",
                "entity_id": nif,
                "entity_name": record.get("name"),
                "ts": record.get("ts"),
                # Insolvência declarada é o sinal mais forte; ser credor é mais fraco.
                "severity": 0.95 if insolvent else 0.55,
                "country": "Portugal",
                "source_index": "finance_cire",
                "source_id": record.get("process"),
                "role": "insolvente" if insolvent else role,
                "court": record.get("court"),
            }
        )


def _collect_people(store: _EntityStore, records: List[Dict[str, Any]]) -> None:
    for record in records:
        person_id = str(record.get("person_id") or "").strip()
        company_nif = str(record.get("company_nif") or "").strip()
        if not person_id or not company_nif:
            continue
        person_ref = f"pessoa:{person_id}"
        if person_ref not in store.entities:
            store.entities[person_ref] = {
                "entity_ref": person_ref,
                "entity_id": person_id,
                "entity_type": "pessoa",
                "name": record.get("person_name"),
                "names": [record["person_name"]] if record.get("person_name") else [],
                "country": "Portugal",
                "roles": ["cargo"],
                "sources": ["people"],
                "contracts_count": 0,
                "contracts_value": 0.0,
                "counterparties": set(),
                "cpv": {},
                "first_seen": record.get("ts"),
                "last_event_at": record.get("ts"),
                "insolvent": False,
                "insolvency_roles": [],
                "dependency": 0.0,
            }
        # A empresa tem de existir no mundo para a aresta ter os dois extremos.
        store.touch(company_nif, record.get("company_name"), "", "Portugal", "people", "empresa")
        role = _clean_text(record.get("role")) or "cargo"
        # Cada anúncio de cargo é um acontecimento (`cargo_iniciado`): as
        # publicações societárias dizem quem passou a exercer, mas **não** dizem
        # quem cessou — por isso não se emite `cargo_cessado`.
        store.add_event(
            {
                "kind": "cargo_iniciado",
                "entity_ref": _ref_for(company_nif),
                "entity_type": "empresa",
                "entity_id": company_nif,
                "entity_name": record.get("company_name"),
                "counterparty_ref": person_ref,
                "counterparty_name": record.get("person_name"),
                "ts": record.get("ts"),
                "value": None,
                "severity": 0.4,
                "country": "Portugal",
                "source_index": "finance_people",
                "source_id": f"{person_id}:{role}",
                "role": role,
            }
        )
        store.add_relation(
            kind="cargo_em",
            source_ref=person_ref,
            source_name=record.get("person_name"),
            source_type="pessoa",
            target_ref=_ref_for(company_nif),
            target_name=record.get("company_name"),
            target_type="empresa",
            ts=record.get("ts"),
            value=None,
            evidence=record.get("role"),
            country="Portugal",
        )


def _finalize(store: _EntityStore, config: Dict[str, Any], version: int, now: str) -> Dict[str, Any]:
    """Calcula estado, risco e atividade por entidade; devolve documentos prontos."""
    # Índices auxiliares: relações por extremo.
    relations_by_ref: Dict[str, List[Dict[str, Any]]] = {}
    for relation in store.relations.values():
        relations_by_ref.setdefault(relation["source_ref"], []).append(relation)
        relations_by_ref.setdefault(relation["target_ref"], []).append(relation)

    events_by_ref: Dict[str, List[Dict[str, Any]]] = {}
    for event in store.events:
        events_by_ref.setdefault(event.get("entity_ref") or "", []).append(event)

    max_events = max((len(v) for v in events_by_ref.values()), default=1)
    recent_limit = datetime.now(timezone.utc) - timedelta(days=365)

    state_docs: List[Dict[str, Any]] = []
    for ref, entity in store.entities.items():
        events = events_by_ref.get(ref, [])
        relations = relations_by_ref.get(ref, [])
        counterparties = len({r["target_ref"] if r["source_ref"] == ref else r["source_ref"] for r in relations})

        # Atividade: eventos nos últimos 12 meses, normalizados pelo máximo.
        recent = 0
        previous = 0
        for event in events:
            ts = event.get("ts")
            if not ts:
                continue
            try:
                when = datetime.fromisoformat(str(ts)[:10]).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if when >= recent_limit:
                recent += 1
            elif when >= recent_limit - timedelta(days=365):
                previous += 1
        activity = _clip(recent / max(1, max_events) * 2.0)
        if recent > previous * 1.2:
            trend = "a crescer"
        elif recent < previous * 0.8:
            trend = "em queda"
        else:
            trend = "estável"

        value = float(entity.get("contracts_value") or 0.0)
        contracts = int(entity.get("contracts_count") or 0)
        # As agregações são autoritativas para as entidades que cobrem; para as
        # restantes, o que se conhece vem da amostra de contratos.
        agg_contracts = contracts
        sample_contracts = int(entity.get("sample_contracts") or 0)
        if agg_contracts:
            value_source = "agregação"
        elif sample_contracts:
            contracts = sample_contracts
            value = float(entity.get("sample_value") or 0.0)
            value_source = "amostra"
        else:
            contracts, value, value_source = 0, 0.0, "sem dados"
        avg_ticket = value / contracts if contracts else 0.0

        # Concentração: peso do maior cliente nas relações **comerciais**
        # (`adjudicou`); os cargos e outras relações não contam como clientes. Só
        # faz sentido com uma amostra mínima — com uma ou duas arestas o valor
        # seria sempre 100% e a conclusão enganadora.
        client_values: Dict[str, float] = {}
        for relation in relations:
            if str(relation.get("kind")) != "adjudicou":
                continue
            counterparty = relation["target_ref"] if relation["source_ref"] == ref else relation["source_ref"]
            client_values[counterparty] = client_values.get(counterparty, 0.0) + float(relation.get("value_sum") or 0.0)
        total = sum(client_values.values()) or 0.0
        concentration_reliable = len(client_values) >= 3
        concentration = (max(client_values.values()) / total) if total and concentration_reliable else 0.0
        dependency = concentration * _clip(contracts / 20.0)

        inactivity_years = 0.0
        last_seen = entity.get("last_event_at") or entity.get("first_seen")
        if last_seen:
            try:
                year = int(str(last_seen)[:4])
                inactivity_years = max(0.0, datetime.now(timezone.utc).year - year)
            except Exception:
                inactivity_years = 0.0

        # Risco: soma ponderada de sinais observáveis (heurística documentada).
        risk = risk_score(
            insolvent=bool(entity.get("insolvent")),
            insolvency_roles=entity.get("insolvency_roles") or [],
            contracts=contracts,
            value=value,
            concentration=concentration,
            inactive_years=inactivity_years,
            config=config,
        )

        if entity.get("insolvent"):
            status = "insolvente"
        elif recent:
            status = "ativo"
        else:
            status = "sem atividade recente" if contracts else "sem contratos"

        top_cpv = None
        if entity.get("cpv"):
            top_cpv = max(entity["cpv"].items(), key=lambda item: item[1])[0]

        state_docs.append(
            {
                "entity_ref": ref,
                "entity_id": entity.get("entity_id"),
                "entity_type": entity.get("entity_type") or _entity_type_for_roles(entity.get("roles") or []),
                "name": entity.get("name") or entity.get("entity_id"),
                "names": (entity.get("names") or [])[:8],
                # Designação normalizada (sem acentos/pontuação): serve as junções
                # por nome das fontes que não têm NIF (GLEIF, imprensa) e a pesquisa.
                "name_folded": sources.fold_name(entity.get("name")),
                "identifiers": entity.get("identifiers") or {},
                "attributes": entity.get("attributes") or {},
                "source_docs": len(entity.get("sources") or []),
                "country": entity.get("country") or "Portugal",
                "roles": entity.get("roles") or [],
                "sources": entity.get("sources") or [],
                "state": {
                    "status": status,
                    "insolvent": bool(entity.get("insolvent")),
                    "insolvency_roles": sorted(set(entity.get("insolvency_roles") or [])),
                    "avg_ticket": round(avg_ticket, 2),
                    "concentration": round(concentration, 4),
                    "concentration_reliable": concentration_reliable,
                    "dependency": round(dependency, 4),
                    "last_seen": last_seen,
                    "activity_trend": trend,
                },
                "metrics": {
                    "contracts": contracts,
                    "value": round(value, 2),
                    "value_source": value_source,
                    "clients": len(client_values),
                    "events": len(events),
                    "relations": len(relations),
                    "counterparties": counterparties,
                    "events_last_year": recent,
                    "events_previous_year": previous,
                    "inactivity_years": inactivity_years,
                },
                "contracts_count": contracts,
                "contracts_value": round(value, 2),
                "relations_count": len(relations),
                "events_count": len(events),
                "counterparties_count": counterparties,
                "cpv_codes": list((entity.get("cpv") or {}).keys())[:20],
                "top_cpv": top_cpv,
                "risk": risk,
                "risk_label": _risk_label(risk, config),
                "activity": round(activity, 4),
                "activity_trend": trend,
                "first_seen": entity.get("first_seen"),
                "last_event_at": last_seen,
                "insolvent": bool(entity.get("insolvent")),
                "world_version": version,
                "updated_at": now,
            }
        )

    event_docs: List[Dict[str, Any]] = []
    for event in store.events:
        ts = event.get("ts")
        year = None
        month = None
        if ts and str(ts)[:4].isdigit():
            year = int(str(ts)[:4])
            month = str(ts)[:7]
        severity = float(event.get("severity") or 0.0)
        event_docs.append(
            {
                "event_id": f"{event.get('kind')}:{event.get('entity_ref')}:{ts}:{event.get('source_id')}",
                "kind": event.get("kind"),
                "kind_label": EVENT_LABELS.get(str(event.get("kind")), str(event.get("kind"))),
                "entity_ref": event.get("entity_ref"),
                "entity_type": event.get("entity_type"),
                "entity_id": event.get("entity_id"),
                "entity_name": event.get("entity_name"),
                "counterparty_ref": event.get("counterparty_ref"),
                "counterparty_name": event.get("counterparty_name"),
                "ts": ts,
                "year": year,
                "month": month,
                "value": event.get("value"),
                "delta": event.get("delta"),
                "severity": round(severity, 4),
                "severity_label": "elevada" if severity >= 0.7 else ("média" if severity >= 0.4 else "baixa"),
                "country": event.get("country"),
                "source_index": event.get("source_index"),
                "source_id": event.get("source_id"),
                "payload": {k: v for k, v in event.items() if k not in {"kind", "entity_ref", "ts"}},
                "world_version": version,
                "detected_at": now,
            }
        )

    relation_docs: List[Dict[str, Any]] = []
    for relation in store.relations.values():
        relation_docs.append(
            {
                **{k: v for k, v in relation.items() if k != "evidence"},
                "kind_label": RELATION_LABELS.get(str(relation.get("kind")), str(relation.get("kind"))),
                "weight": float(relation.get("contracts_count") or 1),
                "status": "ativa",
                "evidence": relation.get("evidence") or [],
                "world_version": version,
                "updated_at": now,
            }
        )

    return {"state": state_docs, "events": event_docs, "relations": relation_docs}


# ---------------------------------------------------------------------------
# Escrita no Elasticsearch
# ---------------------------------------------------------------------------
def _bulk_write(client: Elasticsearch, index: str, docs: List[Dict[str, Any]], id_field: str) -> Tuple[int, int]:
    if not docs:
        return 0, 0
    actions = []
    for doc in docs:
        doc_id = doc.get(id_field)
        action: Dict[str, Any] = {"_index": index, "_source": doc}
        if doc_id:
            action["_id"] = str(doc_id)
        actions.append(action)
    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)
        return int(success), len(errors) if isinstance(errors, list) else 0
    except Exception as exc:
        logger.warning("Bulk para %s falhou: %s", index, exc)
        return 0, len(docs)


def _delete_stale(client: Elasticsearch, version: int) -> Dict[str, int]:
    removed: Dict[str, int] = {}
    for index in (WORLD_STATE_INDEX, WORLD_EVENTS_INDEX, WORLD_RELATIONS_INDEX, WORLD_HISTORY_INDEX):
        try:
            resp = client.delete_by_query(
                index=index,
                body={"query": {"range": {"world_version": {"lt": version}}}},
                conflicts="proceed",
                refresh=True,
                request_timeout=120,
            )
            removed[index] = int(resp.get("deleted") or 0)
        except Exception as exc:
            logger.warning("Limpeza de %s falhou: %s", index, exc)
            removed[index] = -1
    return removed


def _zero_sets(store: _EntityStore) -> None:
    """Remove conjuntos não serializáveis antes de gravar."""
    for entity in store.entities.values():
        entity.pop("counterparties", None)
        entity.pop("cpv", None)


# ---------------------------------------------------------------------------
# Fontes adicionais (associáveis ao Public Data)
# ---------------------------------------------------------------------------
def _known_nifs(store: _EntityStore, limit: int = 25000) -> List[str]:
    """NIF das entidades já no mundo (para as junções por NIF das fontes extra)."""
    out: List[str] = []
    for ref in store.entities:
        if ref.startswith("entidade:"):
            out.append(ref.split(":", 1)[1])
    return sorted(set(out))[:limit]


def _folded_name_index(store: _EntityStore) -> Dict[str, str]:
    """Índice `nome normalizado → entidade`, sem colisões ambíguas.

    Só serve para as fontes que **não têm NIF** (GLEIF por designação legal,
    imprensa por nome no título): quando duas entidades partilham o mesmo nome
    normalizado, o nome sai do índice — mais vale não ligar do que ligar mal.
    """
    index: Dict[str, str] = {}
    ambiguous: set = set()
    for ref, entity in store.entities.items():
        name = entity.get("name")
        if not name:
            continue
        folded = sources.fold_name(name)
        if not folded or len(folded) < 6:
            continue
        if folded in index and index[folded] != ref:
            ambiguous.add(folded)
            continue
        index[folded] = ref
    for folded in ambiguous:
        index.pop(folded, None)
    return index


def _collect_from_registry(
    store: _EntityStore,
    records: List[Dict[str, Any]],
    folded_names: Dict[str, str],
    source_id: str,
) -> Dict[str, Any]:
    """Enriquece entidades com registos oficiais (nome canónico, tipo, LEI, métricas).

    Não **cria** entidades: o registo de contribuintes tem centenas de milhares de
    registos e o mundo passaria a ser um catálogo em vez de um modelo do que os
    contratos, insolvências e cargos mostram. O que faz é corrigir o que existe:
    designação, país, tipo, identificadores e volumetria em falta.
    """
    enriched = 0
    matched_by_name = 0
    ignored = 0
    for record in records:
        nif = record.get("nif")
        ref = _ref_for(nif) if nif else None
        if not ref:
            # Junção por nome (ex.: GLEIF): só liga com designação legal exata.
            ref = folded_names.get(str(record.get("name_folded") or ""))
            if not ref:
                ignored += 1
                continue
            matched_by_name += 1
        entity = store.entities.get(ref)
        if entity is None:
            ignored += 1
            continue
        changed = False
        name = record.get("name")
        if name and not entity.get("name"):
            entity["name"] = name
            changed = True
        if name and name not in (entity.get("names") or []):
            entity.setdefault("names", []).append(name)
            changed = True
        country = record.get("country")
        if country and not entity.get("country"):
            entity["country"] = country
            changed = True
        entity_type = record.get("entity_type")
        if entity_type and entity.get("entity_type") in (None, "outro", "empresa") and entity_type != "empresa":
            entity["entity_type"] = entity_type
            changed = True
        identifiers = record.get("identifiers") or {}
        if identifiers.get("lei"):
            entity.setdefault("identifiers", {})["lei"] = identifiers["lei"]
            changed = True
        extra = record.get("extra") or {}
        counts = extra.get("contracts_count")
        if counts and not int(entity.get("contracts_count") or 0):
            store.add_contract_metrics(nif, int(counts), extra.get("total_value"), None, None)
            changed = True
        if source_id and source_id not in (entity.get("sources") or []):
            entity.setdefault("sources", []).append(source_id)
            changed = True
        if changed:
            enriched += 1
    return {"records": len(records), "enriched": enriched, "by_name": matched_by_name, "ignored": ignored}


def _collect_publications(store: _EntityStore, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Publicações societárias → eventos datados (e entidades que só aí aparecem)."""
    events = 0
    for record in records:
        nif = str(record.get("nif") or "").strip()
        if not nif:
            continue
        name = record.get("name")
        entity = store.entities.get(_ref_for(nif))
        if entity is None:
            entity = store.touch(nif, name, "publicacao", "Portugal", "societario", "empresa")
        elif name and not entity.get("name"):
            entity["name"] = name
        store.add_event(
            {
                "kind": "publicacao_societaria",
                "entity_ref": _ref_for(nif),
                "entity_type": (entity or {}).get("entity_type") or "empresa",
                "entity_id": nif,
                "entity_name": name,
                "ts": record.get("ts"),
                # Um acto publicado é um acontecimento de baixa severidade: o que
                # interessa é a data e o tipo, não o valor.
                "severity": 0.35,
                "country": "Portugal",
                "source_index": record.get("index"),
                "source_id": record.get("id"),
                "act": record.get("act"),
                "act_label": record.get("act_label"),
                "nature": record.get("nature"),
                "place": record.get("place"),
                "url": record.get("url"),
            }
        )
        events += 1
    return {"records": len(records), "events": events, "entities_created": 0}


def _collect_properties(store: _EntityStore, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Marcas (eventos) e firmas/CAE (atributos) por NIF."""
    events = 0
    attributes = 0
    for record in records:
        nif = str(record.get("nif") or "").strip()
        if not nif:
            continue
        entity = store.entities.get(_ref_for(nif))
        if entity is None:
            entity = store.touch(nif, record.get("entity_name"), "propriedade", "Portugal", record.get("source") or "inpi", "empresa")
        if record.get("kind") == "marca":
            store.add_event(
                {
                    "kind": "marca_registada",
                    "entity_ref": _ref_for(nif),
                    "entity_type": (entity or {}).get("entity_type") or "empresa",
                    "entity_id": nif,
                    "entity_name": (entity or {}).get("name") or record.get("entity_name"),
                    "ts": record.get("ts"),
                    "severity": 0.25,
                    "country": "Portugal",
                    "source_index": record.get("index"),
                    "source_id": record.get("id"),
                    "mark": record.get("name"),
                    "mark_type": record.get("detail"),
                    "phase": record.get("phase"),
                    "classes": record.get("classes"),
                }
            )
            events += 1
        else:
            # Firma: atributo estável (CAE e situação), não acontecimento.
            attrs = entity.setdefault("attributes", {}) if entity is not None else {}
            if record.get("detail"):
                attrs["cae"] = record["detail"]
            extra = record.get("extra") or {}
            if extra.get("situacao"):
                attrs["situacao"] = extra["situacao"]
            if extra.get("concelho"):
                attrs["concelho"] = extra["concelho"]
            attributes += 1
    return {"records": len(records), "events": events, "attributes": attributes}


def _text_name_matches(text: str, folded_names: Dict[str, str], max_words: int = 24, max_gram: int = 8) -> List[str]:
    """Entidades cujo nome aparece (contíguo) no texto — para fontes sem NIF.

    Gera n-gramas das primeiras palavras do texto e procura-os no índice de nomes:
    é O(palavras × n) e não O(entidades × documentos). Só nomes com 6+ caracteres
    entram no índice, pelo que «SONAE» não é confundido com uma palavra comum.
    """
    words = re.sub(r"[^0-9A-Za-zÀ-ÿ ]+", " ", str(text or "")).split()
    words = words[:max_words]
    if not words:
        return []
    found: List[str] = []
    for start in range(len(words)):
        for length in range(1, max_gram + 1):
            if start + length > len(words):
                break
            folded = sources.fold_name(" ".join(words[start : start + length]))
            ref = folded_names.get(folded)
            if ref and ref not in found:
                found.append(ref)
    return found


def _collect_mentions(
    store: _EntityStore,
    records: List[Dict[str, Any]],
    folded_names: Dict[str, str],
) -> Dict[str, Any]:
    """Menções externas (redes sociais e imprensa) como eventos das entidades.

    Liga por NIF (`person_nif`) quando existe; sem NIF, liga-se só se o **nome da
    entidade aparecer no texto**. As menções a entidades desconhecidas são
    contadas e descartadas — não se inventam entidades a partir de ruído.
    """
    events = 0
    unmatched = 0
    for record in records:
        refs: List[str] = []
        nif = record.get("nif")
        if nif and _ref_for(nif) in store.entities:
            refs.append(_ref_for(nif))
        if not refs:
            refs = _text_name_matches(record.get("text") or "", folded_names)
        if not refs:
            unmatched += 1
            continue
        score = record.get("sentiment_score")
        sentiment = str(record.get("sentiment") or "").lower()
        # Sentimento negativo é o sinal com interesse; neutro/positivo é contexto.
        if sentiment.startswith("neg") or (isinstance(score, float) and score <= -0.35):
            severity = 0.55
        elif sentiment.startswith("pos") or (isinstance(score, float) and score >= 0.35):
            severity = 0.25
        else:
            severity = 0.3
        for ref in refs:
            entity = store.entities.get(ref) or {}
            store.add_event(
                {
                    "kind": "mencao",
                    "entity_ref": ref,
                    "entity_type": entity.get("entity_type"),
                    "entity_id": entity.get("entity_id"),
                    "entity_name": entity.get("name"),
                    "ts": record.get("ts"),
                    "severity": severity,
                    "country": entity.get("country"),
                    "source_index": record.get("index"),
                    "source_id": record.get("id"),
                    "channel": record.get("channel"),
                    "sentiment": record.get("sentiment"),
                    "sentiment_score": score,
                    "url": record.get("url"),
                    "excerpt": record.get("text"),
                }
            )
            events += 1
    return {"records": len(records), "events": events, "unmatched": unmatched}


# ---------------------------------------------------------------------------
# Fontes associadas (configuração do Public Data)
# ---------------------------------------------------------------------------
def source_overview(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Catálogo de fontes com disponibilidade, volumetria e o que está associado."""
    config = load_config()
    associated = sources.normalize_source_ids(config.get("sources"))
    catalog = sources.availability(es)
    for entry in catalog:
        entry["associated"] = entry["id"] in associated
        entry["required"] = entry["id"] in sources.REQUIRED_SOURCE_IDS
    return {
        "associated": associated,
        "sources": catalog,
        "adapters": sorted({entry["adapter"] for entry in catalog}),
        "counts": sources.source_counts(associated, es),
        "note": "Associar uma fonte só muda o mundo depois de reconstruir (as novas fontes entram no estado, eventos e relações).",
    }


def save_sources(ids: Optional[List[str]]) -> Dict[str, Any]:
    """Grava as fontes associadas (valida ids e garante as obrigatórias)."""
    known = {source["id"] for source in sources.SOURCES}
    unknown = sorted({str(item).strip() for item in (ids or []) if str(item).strip() and str(item).strip() not in known})
    chosen = sources.normalize_source_ids(ids)
    config = save_config({"sources": chosen})
    return {"associated": chosen, "unknown": unknown, "config": config}


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def rebuild(params: Optional[Dict[str, Any]] = None, progress: Optional[Any] = None) -> Dict[str, Any]:
    """Reconstrói o mundo (estado + eventos + relações) a partir dos dados públicos."""
    started = time.time()
    config = load_config()
    config.update({k: v for k, v in (params or {}).items() if v is not None and k in DEFAULT_CONFIG})
    version = int(time.time())
    now = _now()

    client = get_es_client(request_timeout=120)
    if client is None:
        raise RuntimeError("Elasticsearch indisponível — não é possível construir o mundo.")
    ensure_indices(client)

    store = _EntityStore()

    # Só se lê o que está **associado** ao Public Data (ver
    # `world_sources.SOURCES`); as fontes desligadas não entram no mundo.
    associated = sources.normalize_source_ids(config.get("sources"))
    config["sources"] = associated
    extra_stats: Dict[str, Any] = {}

    def _step(label: str, **extra: Any) -> None:
        if progress:
            try:
                progress(label, **extra)
            except Exception:
                pass

    _step("Ler contratos públicos (por papel e país)", sources=associated)
    for role, entity_type, source_id in (
        ("adjudicante", "entidade_publica", "contratos"),
        ("adjudicatario", "empresa", "contratos"),
    ):
        if "contratos" not in associated:
            break
        records = sources.pt_party_metrics(role=role, limit=int(config["entity_limit"]), es=client)
        _collect_from_source_metrics(store, records, role, entity_type, source_id)

    for role, entity_type, source_id in (
        ("adjudicante", "entidade_publica", "contratos_es"),
        ("adjudicatario", "empresa", "contratos_es"),
    ):
        if "contratos_es" not in associated:
            break
        records = sources.es_party_metrics(role=role, limit=int(config["entity_limit"]), es=client)
        _collect_from_source_metrics(store, records, role, entity_type, source_id)

    _step("Ler amostra de contratos (relações e eventos)")
    contracts: List[Dict[str, Any]] = []
    if any(item in associated for item in ("contratos", "contratos_es")):
        contracts = sources.contract_sample(
            size=int(config["contract_sample"]),
            year_from=config.get("year_from"),
            spread_years=int(config.get("contract_years") or 12),
            es=client,
        )
        _collect_from_contracts(store, contracts, version)

    insolvencies: List[Dict[str, Any]] = []
    if "cire" in associated:
        _step("Ler insolvências (CIRE)")
        insolvencies = sources.insolvency_records(size=int(config["insolvency_sample"]), es=client)
        _collect_insolvencies(store, insolvencies)

    people: List[Dict[str, Any]] = []
    if "pessoas" in associated:
        _step("Ler cargos (PessoasIQ)")
        people = sources.people_relations(size=int(config["people_sample"]), es=client)
        _collect_people(store, people)

    # ---- fontes adicionais (associáveis) -------------------------------
    registry_ids = [item for item in associated if sources.SOURCE_BY_ID[item]["adapter"] == "registo"]
    if registry_ids:
        _step("Enriquecer com registos oficiais", sources=registry_ids)
        folded_names = _folded_name_index(store)
        registry = sources.registry_records(
            registry_ids,
            nifs=_known_nifs(store),
            # As junções por nome consultam o campo normalizado do índice, pelo
            # que precisam das designações do mundo (e não de uma amostra dele).
            names=list(folded_names.keys()),
            size=int(config["source_sample"]),
            es=client,
        )
        extra_stats["registo"] = _collect_from_registry(store, registry, folded_names, registry_ids[0])
        extra_stats["registo"]["sources"] = registry_ids

    if "societario" in associated:
        _step("Ler publicações societárias (MJ)")
        publications = sources.publication_records(size=int(config["source_sample"]), es=client)
        extra_stats["societario"] = _collect_publications(store, publications)

    property_ids = [item for item in associated if sources.SOURCE_BY_ID[item]["adapter"] == "propriedade"]
    if property_ids:
        _step("Ler marcas e firmas", sources=property_ids)
        properties = sources.property_records(size=int(config["source_sample"]), es=client)
        extra_stats["propriedade"] = _collect_properties(store, properties)

    mention_ids = [item for item in associated if sources.SOURCE_BY_ID[item]["adapter"] == "mencoes"]
    if mention_ids:
        _step("Ler menções externas", sources=mention_ids)
        mentions = sources.mention_records(size=int(config["source_sample"]), es=client)
        extra_stats["mencoes"] = _collect_mentions(store, mentions, _folded_name_index(store))

    _step("Calcular estado, risco e atividade")
    documents = _finalize(store, config, version, now)

    _step("Reconstruir o estado temporal (histórico por períodos)")
    history_docs = _history_documents(store, config, version, now)
    _zero_sets(store)

    _step("Gravar estado", documents=len(documents["state"]))
    written = {
        "state": _bulk_write(client, WORLD_STATE_INDEX, documents["state"], "entity_ref"),
        "events": _bulk_write(client, WORLD_EVENTS_INDEX, documents["events"], "event_id"),
        "relations": _bulk_write(client, WORLD_RELATIONS_INDEX, documents["relations"], "relation_id"),
        "history": _bulk_write(client, WORLD_HISTORY_INDEX, history_docs, "_history_id"),
    }

    removed: Dict[str, int] = {}
    if config.get("delete_stale"):
        _step("Remover estado obsoleto")
        removed = _delete_stale(client, version)

    summary = {
        "version": version,
        "built_at": now,
        "duration_s": round(time.time() - started, 2),
        "entities": len(documents["state"]),
        "events": len(documents["events"]),
        "relations": len(documents["relations"]),
        "history": len(history_docs),
        "written": {
            index: written[key][0]
            for key, index in (
                ("state", WORLD_STATE_INDEX),
                ("events", WORLD_EVENTS_INDEX),
                ("relations", WORLD_RELATIONS_INDEX),
                ("history", WORLD_HISTORY_INDEX),
            )
        },
        "errors": {
            index: written[key][1]
            for key, index in (
                ("state", WORLD_STATE_INDEX),
                ("events", WORLD_EVENTS_INDEX),
                ("relations", WORLD_RELATIONS_INDEX),
                ("history", WORLD_HISTORY_INDEX),
            )
        },
        "removed": removed,
        "sources_associated": associated,
        "sources": {
            "contratos_amostra": len(contracts),
            "insolvencias": len(insolvencies),
            "cargos": len(people),
            **{key: value for key, value in extra_stats.items() if key in ("societario", "propriedade", "mencoes")},
        },
        "extra": extra_stats,
        "config": config,
    }
    _save_meta({"last_rebuild": summary, "version": version})
    logger.info(
        "World Model reconstruído (v%s): %s entidades, %s eventos, %s relações, %s períodos em %s s",
        version,
        summary["entities"],
        summary["events"],
        summary["relations"],
        summary["history"],
        summary["duration_s"],
    )
    return summary


# ---------------------------------------------------------------------------
# Estado temporal (histórico por períodos)
# ---------------------------------------------------------------------------
def _history_documents(
    store: _EntityStore,
    config: Dict[str, Any],
    version: int,
    now: str,
) -> List[Dict[str, Any]]:
    """Constrói o **estado temporal**: um documento por entidade e por período.

    O que o estado atual não permite responder é «como chegou a este estado?».
    Aqui reconstrói-se, a partir da linha temporal de eventos e das relações:

    - contadores **do período** (contratos, valor, eventos por tipo, contrapartes novas);
    - contadores **acumulados** até ao fim do período (o estado nesse dia);
    - **risco recalculado** no fim do período, com a mesma fórmula do estado atual
      (`risk_score`), para a série ser comparável;
    - deltas face ao período anterior.

    Limitações assumidas: a concentração/administradores usam as relações
    conhecidas até ao fim do período (o valor por relação é o total, não o do
    período) e os cargos só têm a data de anúncio (não há cessação na fonte).
    """
    grain = str(config.get("history_grain") or "quarter")
    max_periods = int(config.get("history_max_periods") or 24)

    relations_by_ref: Dict[str, List[Dict[str, Any]]] = {}
    for relation in store.relations.values():
        for end_ref in (relation.get("source_ref"), relation.get("target_ref")):
            if end_ref:
                relations_by_ref.setdefault(end_ref, []).append(relation)

    events_by_ref: Dict[str, List[Dict[str, Any]]] = {}
    for event in store.events:
        ref = event.get("entity_ref") or ""
        if ref and event.get("ts"):
            events_by_ref.setdefault(ref, []).append(event)

    documents: List[Dict[str, Any]] = []
    for ref, entity in store.entities.items():
        events = sorted(events_by_ref.get(ref, []), key=lambda item: str(item.get("ts")))
        relations = relations_by_ref.get(ref, [])
        if not events and not relations:
            continue

        # --- contrapartes: primeira vez que aparecem -------------------------
        counterparty_first: Dict[str, str] = {}
        for relation in relations:
            other = relation.get("target_ref") if relation.get("source_ref") == ref else relation.get("source_ref")
            ts = relation.get("first_ts")
            if other and ts and (other not in counterparty_first or str(ts) < counterparty_first[other]):
                counterparty_first[other] = str(ts)

        periods: Dict[str, Dict[str, Any]] = {}

        def _bucket(ts: str) -> Optional[Dict[str, Any]]:
            period = _period_of(ts, grain)
            if not period:
                return None
            key, start, end = period
            return periods.setdefault(
                key,
                {
                    "period": key,
                    "period_start": start,
                    "period_end": end,
                    "contracts": 0,
                    "value": 0.0,
                    "events": 0,
                    "kinds": {},
                    "new_counterparties": set(),
                    "first_contract": None,
                },
            )

        for event in events:
            bucket = _bucket(str(event.get("ts")))
            if bucket is None:
                continue
            kind = str(event.get("kind") or "?")
            bucket["events"] += 1
            bucket["kinds"][kind] = bucket["kinds"].get(kind, 0) + 1
            if kind == "adjudicacao":
                bucket["contracts"] += 1
                bucket["value"] += float(event.get("value") or 0.0)

        for other, ts in counterparty_first.items():
            bucket = _bucket(ts)
            if bucket is not None:
                bucket["new_counterparties"].add(other)

        if not periods:
            continue

        keys = sorted(periods)
        window = keys[-max_periods:]
        cum_contracts = 0
        cum_value = 0.0
        cum_counterparties: set = set()
        cum_directors: set = set()
        insolvent_until = False
        previous_contracts = 0
        previous_value = 0.0

        for key in keys:
            bucket = periods[key]
            cum_contracts += int(bucket["contracts"])
            cum_value += float(bucket["value"])
            cum_counterparties |= set(bucket["new_counterparties"])
            for event in events:
                if not str(event.get("ts", "")).startswith(key[:4]):
                    continue
                if _period_of(str(event.get("ts")), grain)[0] != key:  # type: ignore[index]
                    continue
                if event.get("kind") == "cargo_iniciado" and event.get("counterparty_ref"):
                    cum_directors.add(str(event.get("counterparty_ref")))
                if event.get("kind") == "insolvencia":
                    insolvent_until = True

            if key not in window:
                previous_contracts, previous_value = cum_contracts, cum_value
                continue

            # Concentração até ao fim do período: só relações já conhecidas então,
            # e apenas comerciais (os cargos não são clientes).
            client_values: Dict[str, float] = {}
            for relation in relations:
                if str(relation.get("kind")) != "adjudicou":
                    continue
                first_ts = relation.get("first_ts")
                if not first_ts or str(first_ts) > bucket["period_end"]:
                    continue
                other = relation.get("target_ref") if relation.get("source_ref") == ref else relation.get("source_ref")
                if other:
                    client_values[other] = client_values.get(other, 0.0) + float(relation.get("value_sum") or 0.0)
            total = sum(client_values.values()) or 0.0
            concentration = (max(client_values.values()) / total) if total and len(client_values) >= 3 else 0.0

            # Inatividade no fim do período: anos desde o último evento conhecido.
            last_ts = max((str(event.get("ts")) for event in events if str(event.get("ts")) <= bucket["period_end"]), default=None)
            try:
                inactive_years = max(0.0, int(str(bucket["period_end"])[:4]) - int(str(last_ts)[:4])) if last_ts else 0.0
            except ValueError:
                inactive_years = 0.0

            risk = risk_score(
                insolvent=insolvent_until,
                insolvency_roles=entity.get("insolvency_roles") if insolvent_until else [],
                contracts=cum_contracts,
                value=cum_value,
                concentration=concentration,
                inactive_years=inactive_years,
                config=config,
            )
            documents.append(
                {
                    "_history_id": f"{ref}@{grain}@{key}",
                    "entity_ref": ref,
                    "entity_id": entity.get("entity_id"),
                    "entity_type": entity.get("entity_type"),
                    "name": entity.get("name"),
                    "country": entity.get("country"),
                    "grain": grain,
                    "period": key,
                    "period_start": bucket["period_start"],
                    "period_end": bucket["period_end"],
                    "contracts": int(bucket["contracts"]),
                    "value": round(float(bucket["value"]), 2),
                    "events": int(bucket["events"]),
                    "kinds": dict(bucket["kinds"]),
                    "new_counterparties": len(bucket["new_counterparties"]),
                    "first_contract": None,
                    "cum_contracts": cum_contracts,
                    "cum_value": round(cum_value, 2),
                    "cum_counterparties": len(cum_counterparties),
                    "cum_directors": len(cum_directors),
                    "insolvent": insolvent_until,
                    "risk": risk,
                    "risk_label": _risk_label(risk, config),
                    "delta_contracts": int(bucket["contracts"]) - previous_contracts,
                    "delta_value": round(float(bucket["value"]) - previous_value, 2),
                    "status": "insolvente" if insolvent_until else ("ativo" if bucket["events"] else "sem atividade"),
                    "world_version": version,
                    "updated_at": now,
                }
            )
            previous_contracts = int(bucket["contracts"])
            previous_value = float(bucket["value"])

    return documents


def history(
    entity_ref: Optional[str] = None,
    grain: Optional[str] = None,
    limit: int = 200,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Série temporal de uma entidade (por períodos) ou a mais recente do mundo."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return {"error": "Elasticsearch indisponível", "series": []}
    filters: List[Dict[str, Any]] = []
    if entity_ref:
        value = str(entity_ref).strip()
        filters.append({"bool": {"should": [{"term": {"entity_ref": value}}, {"term": {"entity_ref": _ref_for(value)}}], "minimum_should_match": 1}})
    if grain:
        filters.append({"term": {"grain": grain}})
    body = {
        "size": max(1, min(2000, int(limit))),
        "track_total_hits": True,
        "query": {"bool": {"filter": filters}},
        "sort": [{"period_start": {"order": "asc"}}],
    }
    try:
        resp = client.search(index=WORLD_HISTORY_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)[:300], "series": []}
    hits = (resp.get("hits") or {}).get("hits") or []
    return {
        "entity_ref": entity_ref,
        "total": ((resp.get("hits") or {}).get("total") or {}).get("value", len(hits)),
        "series": [_hit(hit) for hit in hits],
    }


def history_series(grain: str = "quarter", limit: int = 40, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Série agregada do mundo: contratos, valor e novos clientes por período."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return {"error": "Elasticsearch indisponível", "series": []}
    body = {
        "size": 0,
        "track_total_hits": False,
        "query": {"bool": {"filter": [{"term": {"grain": grain}}]}},
        "aggs": {
            "by_period": {
                # `period` é uma chave ordenável (`2026-Q3`), o que permite usar
                # `_key` para ordenar sem scripts.
                "terms": {"field": "period", "size": max(1, min(200, int(limit))), "order": {"_key": "desc"}},
                "aggs": {
                    "contracts": {"sum": {"field": "contracts"}},
                    "value": {"sum": {"field": "value"}},
                    "new_counterparties": {"sum": {"field": "new_counterparties"}},
                    "entities": {"cardinality": {"field": "entity_ref", "precision_threshold": 40000}},
                    "kinds": {"terms": {"field": "kinds", "size": 8}},
                },
            }
        },
    }
    try:
        resp = client.search(index=WORLD_HISTORY_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)[:300], "series": []}
    buckets = ((resp.get("aggregations") or {}).get("by_period") or {}).get("buckets") or []
    # A agregação traz os períodos **mais recentes** (ordem descendente, para
    # respeitar o `limit`); devolvem-se cronologicamente.
    return {
        "grain": grain,
        "series": [
            {
                "period": bucket["key"],
                "entities": int(bucket.get("doc_count") or 0),
                "contracts": int(((bucket.get("contracts") or {}).get("value") or 0)),
                "value": round(((bucket.get("value") or {}).get("value") or 0.0), 2),
                "new_counterparties": int(((bucket.get("new_counterparties") or {}).get("value") or 0)),
                "kinds": [{"key": b["key"], "count": b["doc_count"]} for b in (bucket.get("kinds") or {}).get("buckets", [])],
            }
            for bucket in reversed(buckets)
        ],
    }


# ---------------------------------------------------------------------------
# Grafo de execução do pipeline
# ---------------------------------------------------------------------------
#: Ligações entre as camadas do pipeline e os artefactos que produzem.
_PIPELINE_EDGES: List[Tuple[str, str, str]] = [
    ("public-data", "world-model", "lê índices"),
    ("world-model", "dynamic-network", "estado + relações"),
    ("world-model", "graph-temporal", "relações + eventos"),
    ("dynamic-network", "future-simulator", "previsão + anomalias"),
    ("graph-temporal", "future-simulator", "causalidade + séries"),
    ("future-simulator", "investigation-agent", "cenários"),
    ("dynamic-network", "investigation-agent", "alvos (anomalias)"),
    ("graph-temporal", "investigation-agent", "evidência"),
    ("investigation-agent", "evidence-graph", "afirmações + fontes"),
]

#: Estágios que não constam do diagrama original mas fecham o ciclo de auditoria
#: (o grafo de evidências é produzido pelo agente). São nós do mesmo grafo.
_PIPELINE_EXTRA_STAGES: List[Dict[str, Any]] = [
    {
        "id": "evidence-graph",
        "label": "Evidence Graph",
        "hint": "Liga cada conclusão às fontes que a sustentam",
        "backend": "world_agent.py",
    }
]

#: Todos os estágios do pipeline (camadas + estágios de auditoria).
PIPELINE_STAGES: List[Dict[str, Any]] = [*ARCHITECTURE, *_PIPELINE_EXTRA_STAGES]


def pipeline_graph(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """O pipeline **em execução** como grafo: camadas, artefactos e volumetria real.

    Devolve nós (com contagens ao vivo), arestas, um diagrama **Mermaid** pronto a
    colar num relatório e as métricas de cada camada.
    """
    status = index_status(es)
    indexes = status.get("indexes") or {}
    documents = {key: (value or {}).get("documents") or 0 for key, value in indexes.items()}
    saved = _load_meta()
    last = saved.get("last_rebuild") or {}

    # O nó «Public Data» mostra exatamente as **fontes associadas** (não uma lista
    # fixa): o que se vê no grafo é o que a reconstrução lê.
    config = load_config()
    associated = sources.normalize_source_ids(config.get("sources"))
    source_docs = sources.source_counts(associated, es)
    public_artifacts = [
        {
            "label": sources.SOURCE_BY_ID[source_id]["label"],
            "id": source_id,
            "index": sources.SOURCE_BY_ID[source_id]["index"],
            "adapter": sources.SOURCE_BY_ID[source_id]["adapter"],
            "contributes": sources.SOURCE_BY_ID[source_id]["contributes"],
            "documents": source_docs.get(source_id),
        }
        for source_id in associated
        if source_id in sources.SOURCE_BY_ID
    ]

    artifacts = {
        "public-data": public_artifacts,
        "world-model": [
            {"label": WORLD_STATE_INDEX, "documents": documents.get("state", 0)},
            {"label": WORLD_EVENTS_INDEX, "documents": documents.get("events", 0)},
            {"label": WORLD_RELATIONS_INDEX, "documents": documents.get("relations", 0)},
            {"label": WORLD_HISTORY_INDEX, "documents": documents.get("history", 0)},
        ],
        "dynamic-network": [{"label": NETWORK_STATE_LABEL, "documents": documents.get("network", 0)}],
        "graph-temporal": [
            {"label": "consultas de grafo", "documents": None},
            {"label": "consultas temporais", "documents": None},
        ],
        "future-simulator": [{"label": SIMULATIONS_LABEL, "documents": documents.get("simulations", 0)}],
        "investigation-agent": [{"label": INVESTIGATIONS_LABEL, "documents": documents.get("investigations", 0)}],
        "evidence-graph": [{"label": "afirmações com fonte", "documents": None}],
    }

    # Nós = camadas do diagrama + estágios de auditoria (grafo de evidências),
    # para que o grafo em execução tenha todos os extremos das arestas.
    nodes: List[Dict[str, Any]] = []
    for position, layer in enumerate(PIPELINE_STAGES):
        layer_id = layer["id"]
        nodes.append(
            {
                "id": layer_id,
                "label": layer["label"],
                "hint": layer["hint"],
                "backend": layer["backend"],
                "dimension": "camada",
                "type": "stage",
                "position": position,
                "artifacts": artifacts.get(layer_id, []),
                "documents": sum(item["documents"] or 0 for item in artifacts.get(layer_id, [])),
            }
        )

    edges = [{"id": f"{a}->{b}", "source": a, "target": b, "label": label, "kind": "fluxo"} for a, b, label in _PIPELINE_EDGES]

    mermaid = ["flowchart TD"]
    ids = MermaidIds()
    for node in nodes:
        count = f"<br/>{_fmt_int(node['documents'])} docs" if node["documents"] else ""
        mermaid.append(f"    {ids(node['id'])}[\"{mermaid_label(node['label'])}{count}\"]")
    for edge in edges:
        mermaid.append(
            f"    {ids(edge['source'])} -->|{mermaid_edge_label(edge['label'], limit=40)}| {ids(edge['target'])}"
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "mermaid": "\n".join(mermaid),
        "metrics": {
            "layers": len(nodes),
            "edges": len(edges),
            "documents": sum(documents.values()),
            "last_rebuild": last.get("built_at"),
            "version": saved.get("version"),
        },
    }


NETWORK_STATE_LABEL = "finance_network_state"
SIMULATIONS_LABEL = "finance_world_simulations"
INVESTIGATIONS_LABEL = "finance_world_investigations"


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def index_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria e distribuições dos índices do mundo."""
    client = es or get_es_client(request_timeout=60)
    out: Dict[str, Any] = {"available": client is not None, "indexes": {}, "distributions": {}}
    if client is None:
        return out
    for key, index in (
        ("state", WORLD_STATE_INDEX),
        ("events", WORLD_EVENTS_INDEX),
        ("relations", WORLD_RELATIONS_INDEX),
        ("history", WORLD_HISTORY_INDEX),
    ):
        try:
            out["indexes"][key] = {"index": index, "documents": int(client.count(index=index)["count"])}
        except Exception as exc:
            out["indexes"][key] = {"index": index, "documents": 0, "error": str(exc)[:200]}
    try:
        body = {
            "size": 0,
            "track_total_hits": False,
            "aggs": {
                "types": {"terms": {"field": "entity_type", "size": 12}},
                "countries": {"terms": {"field": "country", "size": 12}},
                "risk": {"terms": {"field": "risk_label", "size": 6}},
                "top_value": {"terms": {"field": "name.keyword", "size": 8, "order": {"valor": "desc"}},
                              "aggs": {"valor": {"max": {"field": "contracts_value"}}}},
                "top_risk": {"terms": {"field": "name.keyword", "size": 8, "order": {"r": "desc"}},
                             "aggs": {"r": {"max": {"field": "risk"}}}},
            },
        }
        resp = client.search(index=WORLD_STATE_INDEX, body=body)
        aggs = resp.get("aggregations") or {}
        out["distributions"] = {
            "entity_types": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("types") or {}).get("buckets", [])],
            "countries": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("countries") or {}).get("buckets", [])],
            "risk_labels": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("risk") or {}).get("buckets", [])],
            "top_value": [
                {"key": b["key"], "value": round((b.get("valor") or {}).get("value") or 0.0, 2)}
                for b in (aggs.get("top_value") or {}).get("buckets", [])
            ],
            "top_risk": [
                {"key": b["key"], "risk": round((b.get("r") or {}).get("value") or 0.0, 4)}
                for b in (aggs.get("top_risk") or {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        out["distributions_error"] = str(exc)[:300]
    return out


def status() -> Dict[str, Any]:
    """Estado completo do módulo (volumetria + configuração + último rebuild)."""
    config = load_config()
    saved = _load_meta()
    payload = index_status()
    payload["config"] = config
    payload["last_rebuild"] = saved.get("last_rebuild")
    payload["version"] = saved.get("version")
    payload["available_sources"] = sources.availability()
    return payload


def search_entities(
    q: Optional[str] = None,
    entity_type: Optional[str] = None,
    country: Optional[str] = None,
    risk_label: Optional[str] = None,
    insolvent: Optional[bool] = None,
    role: Optional[str] = None,
    sort: str = "relevance",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa entidades do mundo com filtros e ordenação."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return {"error": "Elasticsearch indisponível", "total": 0, "results": []}

    filters: List[Dict[str, Any]] = []
    if entity_type:
        filters.append({"term": {"entity_type": entity_type}})
    if country:
        filters.append({"term": {"country": country}})
    if risk_label:
        filters.append({"term": {"risk_label": risk_label}})
    if insolvent is not None:
        filters.append({"term": {"insolvent": bool(insolvent)}})
    if role:
        filters.append({"term": {"roles": role}})

    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["name^3", "name_folded^2", "entity_id^3", "names^2"],
                    "fuzziness": "AUTO",
                }
            }
        )

    orders = {
        "relevance": ["_score", {"contracts_value": "desc"}],
        "value": [{"contracts_value": "desc"}],
        "contracts": [{"contracts_count": "desc"}],
        "risk": [{"risk": "desc"}],
        "activity": [{"activity": "desc"}],
        "relations": [{"relations_count": "desc"}],
        "recent": [{"last_event_at": "desc"}],
        "name": [{"name.keyword": "asc"}],
    }
    body = {
        "size": max(1, min(200, int(size))),
        "from": max(0, int(from_)),
        "track_total_hits": True,
        "query": {"bool": {"filter": filters, "must": must}},
        "sort": orders.get(sort, orders["relevance"]),
    }
    try:
        resp = client.search(index=WORLD_STATE_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)[:300], "total": 0, "results": []}
    hits = (resp.get("hits") or {}).get("hits") or []
    return {
        "total": ((resp.get("hits") or {}).get("total") or {}).get("value", len(hits)),
        "results": [_hit(hit) for hit in hits],
    }


def _hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    source = dict(hit.get("_source") or {})
    source["_score"] = hit.get("_score")
    return source


def get_entity(ref_or_id: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Ficha de uma entidade do mundo (por `entity_ref`, NIF/NIPC ou id)."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return None
    value = str(ref_or_id or "").strip()
    if not value:
        return None
    candidates = [value, _ref_for(value), f"pessoa:{value}"]
    for candidate in candidates:
        try:
            resp = client.get(index=WORLD_STATE_INDEX, id=candidate, ignore=[404])
        except Exception:
            continue
        if resp.get("found"):
            return resp.get("_source")
    # Fallback: procurar pelo identificador.
    try:
        resp = client.search(
            index=WORLD_STATE_INDEX,
            body={"size": 1, "query": {"term": {"entity_id": value}}},
        )
        hits = (resp.get("hits") or {}).get("hits") or []
        return _hit(hits[0]) if hits else None
    except Exception:
        return None


def timeline(
    entity_ref: Optional[str] = None,
    kind: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    size: int = 50,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Linha temporal de eventos (por entidade e/ou tipo e/ou janela de anos)."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return {"error": "Elasticsearch indisponível", "total": 0, "events": []}
    filters: List[Dict[str, Any]] = []
    if entity_ref:
        value = str(entity_ref).strip()
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"entity_ref": value}},
                        {"term": {"entity_ref": _ref_for(value)}},
                        {"term": {"counterparty_ref": value}},
                        {"term": {"counterparty_ref": _ref_for(value)}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if kind:
        filters.append({"terms": {"kind": [k.strip() for k in str(kind).split(",") if k.strip()]}})
    if year_from or year_to:
        filters.append({"range": {"year": {"gte": year_from or 1900, "lte": year_to or 2200}}})
    body = {
        "size": max(1, min(500, int(size))),
        "track_total_hits": True,
        "query": {"bool": {"filter": filters}},
        "sort": [{"ts": {"order": "desc", "missing": "_last"}}],
        "_source": {"excludes": ["payload"]},
    }
    try:
        resp = client.search(index=WORLD_EVENTS_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)[:300], "total": 0, "events": []}
    hits = (resp.get("hits") or {}).get("hits") or []
    return {
        "total": ((resp.get("hits") or {}).get("total") or {}).get("value", len(hits)),
        "events": [_hit(hit) for hit in hits],
    }


def event_stats(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Distribuições de eventos (tipo, ano, severidade) para gráficos."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return {}
    body = {
        "size": 0,
        "track_total_hits": False,
        "aggs": {
            "kinds": {"terms": {"field": "kind", "size": 12}},
            "years": {"terms": {"field": "year", "size": 30, "order": {"_key": "asc"}}},
            "severity": {"terms": {"field": "severity_label", "size": 6}},
        },
    }
    try:
        resp = client.search(index=WORLD_EVENTS_INDEX, body=body)
    except Exception:
        return {}
    aggs = resp.get("aggregations") or {}
    return {
        "kinds": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("kinds") or {}).get("buckets", [])],
        "years": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("years") or {}).get("buckets", [])],
        "severity": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("severity") or {}).get("buckets", [])],
    }


def relations(
    entity_ref: Optional[str] = None,
    kind: Optional[str] = None,
    size: int = 100,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Arestas do grafo, opcionalmente de uma só entidade."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return {"error": "Elasticsearch indisponível", "total": 0, "relations": []}
    filters: List[Dict[str, Any]] = []
    if kind:
        filters.append({"terms": {"kind": [k.strip() for k in str(kind).split(",") if k.strip()]}})
    if entity_ref:
        value = str(entity_ref).strip()
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"source_ref": value}},
                        {"term": {"target_ref": value}},
                        {"term": {"source_ref": _ref_for(value)}},
                        {"term": {"target_ref": _ref_for(value)}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    body = {
        "size": max(1, min(1000, int(size))),
        "track_total_hits": True,
        "query": {"bool": {"filter": filters}},
        "sort": [{"value_sum": {"order": "desc", "missing": "_last"}}],
    }
    try:
        resp = client.search(index=WORLD_RELATIONS_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)[:300], "total": 0, "relations": []}
    hits = (resp.get("hits") or {}).get("hits") or []
    return {
        "total": ((resp.get("hits") or {}).get("total") or {}).get("value", len(hits)),
        "relations": [_hit(hit) for hit in hits],
    }


def relation_stats(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Distribuições de relações (tipo) e totais agregados."""
    client = es or get_es_client(request_timeout=60)
    if client is None:
        return {}
    body = {
        "size": 0,
        "track_total_hits": False,
        "aggs": {
            "kinds": {"terms": {"field": "kind", "size": 12}},
            "total_value": {"sum": {"field": "value_sum"}},
            "value_stats": {"stats": {"field": "value_sum"}},
        },
    }
    try:
        resp = client.search(index=WORLD_RELATIONS_INDEX, body=body)
    except Exception:
        return {}
    aggs = resp.get("aggregations") or {}
    return {
        "kinds": [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("kinds") or {}).get("buckets", [])],
        "total_value": round(((aggs.get("total_value") or {}).get("value") or 0.0), 2),
        "value_stats": aggs.get("value_stats") or {},
    }


# ---------------------------------------------------------------------------
# Jobs (reconstrução em segundo plano)
# ---------------------------------------------------------------------------
def new_run_id() -> str:
    return f"world-{uuid.uuid4().hex[:10]}"
