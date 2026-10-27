"""Serviço do **modelo de contratos** (`/llm/modelo/*`).

Junta as três peças que o treino produz num sítio só, para a API e a página do
modelo não terem de saber onde estão os ficheiros:

- `model/qwen05-contratos/` — adaptador LoRA (o resultado do fine-tuning);
- `metrics.jsonl` — a curva de perda, uma linha por actualização;
- `run_metadata.json` — o que foi treinado, com que dados e em quanto tempo.

O histórico de avaliações vai para o Elasticsearch (`finance_llm_model_evals`),
porque é a memória que sobrevive a uma recriação do contentor — o `eval.json` no
disco é só a última corrida.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from inference import contratos_lora

logger = logging.getLogger(__name__)

MODEL_RUNS_INDEX = "finance_llm_model_runs"
MODEL_EVALS_INDEX = "finance_llm_model_evals"

ROOT = Path(__file__).resolve().parents[1]
METRICS_FILE = contratos_lora.DEFAULT_ADAPTER_DIR / "metrics.jsonl"

_indices_ready = False
_indices_lock = threading.Lock()
_eval_lock = threading.Lock()

MAPPINGS: Dict[str, Dict[str, Any]] = {
    MODEL_RUNS_INDEX: {
        "properties": {
            "modelo_base": {"type": "keyword"},
            "adaptador": {"type": "keyword"},
            "estado": {"type": "keyword"},
            "metricas": {
                "properties": {
                    "pares_treino": {"type": "integer"},
                    "pares_holdout": {"type": "integer"},
                    "passos": {"type": "integer"},
                    "perda_final": {"type": "float"},
                    "segundos": {"type": "float"},
                }
            },
            "fontes": {"type": "keyword"},
            "ficheiro_metricas": {"type": "keyword"},
            "criado_em": {"type": "date"},
        }
    },
    MODEL_EVALS_INDEX: {
        "properties": {
            "modelo_base": {"type": "keyword"},
            "adaptador": {"type": "keyword"},
            "conjunto": {
                "properties": {
                    "pares": {"type": "integer"},
                    "ficheiro": {"type": "keyword"},
                    "origem": {"type": "keyword"},
                }
            },
            "base": {"properties": {"perplexidade": {"type": "float"}, "exactidao_token": {"type": "float"}}},
            "treinado": {"properties": {"perplexidade": {"type": "float"}, "exactidao_token": {"type": "float"}}},
            "delta": {
                "properties": {
                    "perplexidade": {"type": "float"},
                    "exactidao_token": {"type": "float"},
                    "f1_medio": {"type": "float"},
                }
            },
            "f1_medio": {"type": "float"},
            "fidelidade_numerica": {"type": "float"},
            "amostras": {"enabled": False},
            "criado_em": {"type": "date"},
        }
    },
}


def _client():
    """Cliente do Elasticsearch, ou `None` quando está indisponível."""
    from api.elasticsearch_client import get_es_client

    return get_es_client()


def ensure_indices(es=None) -> bool:
    """Cria os índices do modelo (idempotente, uma vez por processo)."""
    global _indices_ready
    if _indices_ready:
        return True
    client = es or _client()
    if not client:
        return False
    with _indices_lock:
        if _indices_ready:
            return True
        try:
            for index, mapping in MAPPINGS.items():
                if not client.indices.exists(index=index):
                    client.indices.create(index=index, mappings=mapping)
            _indices_ready = True
            return True
        except Exception as exc:  # pragma: no cover - depende do cluster
            logger.warning("Não foi possível criar os índices do modelo: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Estado do modelo
# ---------------------------------------------------------------------------


def read_metrics(limit: int = 200) -> List[Dict[str, Any]]:
    """Últimas `limit` linhas de `metrics.jsonl` (a curva de perda do treino)."""
    path = METRICS_FILE
    if not path.exists():
        return []
    linhas: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        linhas.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        return []
    return linhas[-limit:] if limit else linhas


def model_state() -> Dict[str, Any]:
    """Ficha do modelo: adaptador presente, metadados do treino e curva de perda."""
    adapter_dir = contratos_lora.DEFAULT_ADAPTER_DIR
    disponivel = contratos_lora.adapter_available(adapter_dir)
    metadados = contratos_lora.read_run_metadata(adapter_dir)
    metricas = read_metrics(limit=400)
    ultimo = metricas[-1] if metricas else None
    return {
        "modelo_base": contratos_lora.DEFAULT_BASE_MODEL,
        "adaptador": str(adapter_dir),
        "adaptador_disponivel": disponivel,
        "pausado": (ROOT / "training" / "pause.flag").exists(),
        "treino": metadados,
        "metricas": {
            "pontos": len(metricas),
            "ultima_perda": ultimo.get("perda") if ultimo else None,
            "ultima_perplexidade": ultimo.get("perplexidade") if ultimo else None,
            "tokens": ultimo.get("tokens") if ultimo else None,
            "curva": metricas,
        },
        "fonte_dados": {
            "ficheiro": "data/final/iqos_contratos_empresas_qwen.jsonl",
            "indices": ["contratos", "finance_entities", "finance_subvencoes"],
            "exportador": "training/export_es_dataset.py",
        },
        "verificado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# Inferência
# ---------------------------------------------------------------------------


def chat(instrucao: str, dados: str, max_new_tokens: int = 160, temperatura: float = 0.2) -> Dict[str, Any]:
    """Resposta do modelo afinado para um documento (chamar em threadpool)."""
    return contratos_lora.answer(
        instrucao,
        dados,
        max_new_tokens=max_new_tokens,
        temperature=temperatura,
    )


# ---------------------------------------------------------------------------
# Avaliação e índice
# ---------------------------------------------------------------------------


def avaliar(limite: int = 8, gerar: int = 2, holdout: int = 60, seed: int = 42) -> Dict[str, Any]:
    """Corre a avaliação base vs adaptador num subconjunto do held-out.

    Serializado por `_eval_lock`: dois pedidos em simultâneo duplicariam o custo
    e o segundo não traria informação nova (é o mesmo conjunto, o mesmo modelo).
    """
    from inference.contratos_eval import evaluate

    with _eval_lock:
        resultado = evaluate(holdout=holdout, seed=seed, limite=limite, gerar=gerar)
    resultado["origem"] = "api"
    doc_id = index_eval(resultado)
    resultado["documento"] = doc_id
    return resultado


def _resumo_eval(resultado: Dict[str, Any]) -> Dict[str, Any]:
    treinado = resultado.get("treinado") or {}
    base = resultado.get("base") or {}
    geracao = (treinado.get("geracao") or {})
    return {
        "modelo_base": contratos_lora.DEFAULT_BASE_MODEL,
        "adaptador": str(contratos_lora.DEFAULT_ADAPTER_DIR),
        "conjunto": resultado.get("conjunto") or {},
        "base": {k: base.get(k) for k in ("perplexidade", "exactidao_token", "perda_por_token")},
        "treinado": {k: treinado.get(k) for k in ("perplexidade", "exactidao_token", "perda_por_token")},
        "delta": resultado.get("delta") or {},
        "f1_medio": geracao.get("f1_medio"),
        "fidelidade_numerica": geracao.get("fidelidade_numerica"),
        "amostras": (geracao.get("amostras") or [])[:3],
        "duracao_s": resultado.get("duracao_s"),
        "criado_em": resultado.get("criado_em") or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def index_eval(resultado: Dict[str, Any]) -> Optional[str]:
    """Guarda um resultado de avaliação em `finance_llm_model_evals`."""
    client = _client()
    if not client or not ensure_indices(client):
        return None
    doc_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    try:
        client.index(index=MODEL_EVALS_INDEX, id=doc_id, document=_resumo_eval(resultado))
        return doc_id
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Não foi possível indexar a avaliação: %s", exc)
        return None


def index_run(metadados: Dict[str, Any]) -> Optional[str]:
    """Guarda a ficha de um treino em `finance_llm_model_runs`."""
    client = _client()
    if not client or not ensure_indices(client):
        return None
    treino = metadados.get("treino") or {}
    dados = metadados.get("dados") or {}
    doc_id = f"{(metadados.get('adaptador') or 'run')}-{int(time.time())}"
    try:
        client.index(
            index=MODEL_RUNS_INDEX,
            id=doc_id,
            document={
                "modelo_base": metadados.get("modelo_base"),
                "adaptador": metadados.get("adaptador"),
                "estado": metadados.get("estado"),
                "metricas": {
                    "pares_treino": dados.get("pares_treino"),
                    "pares_holdout": dados.get("pares_holdout"),
                    "passos": treino.get("passos"),
                    "perda_final": treino.get("perda_final"),
                    "segundos": treino.get("segundos"),
                },
                "fontes": dados.get("fontes") or [],
                "ficheiro_metricas": dados.get("ficheiro"),
                "criado_em": treino.get("concluido_em") or time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        return doc_id
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Não foi possível indexar o treino: %s", exc)
        return None


def list_evals(size: int = 20) -> List[Dict[str, Any]]:
    """Histórico de avaliações (mais recentes primeiro)."""
    client = _client()
    if not client or not ensure_indices(client):
        return []
    try:
        resposta = client.search(
            index=MODEL_EVALS_INDEX,
            size=size,
            sort=[{"criado_em": {"order": "desc"}}],
            query={"match_all": {}},
        )
        docs = []
        for hit in resposta.get("hits", {}).get("hits", []):
            doc = dict(hit.get("_source") or {})
            doc["id"] = hit.get("_id")
            docs.append(doc)
        return docs
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Não foi possível ler o histórico de avaliações: %s", exc)
        return []
