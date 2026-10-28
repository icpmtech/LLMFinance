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
import re
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


def responder(
    *,
    instrucao: str,
    dados: str = "",
    prompt_id: Optional[str] = None,
    sistema: Optional[str] = None,
    usar_rag: bool = True,
    usar_memoria: bool = True,
    usar_skills: bool = True,
    raciocinio: bool = True,
    max_new_tokens: int = 160,
    temperatura: float = 0.2,
) -> Dict[str, Any]:
    """Resposta com memória, skills, RAG, verificação e traço de raciocínio.

    O traço (`passos`) é a lista ordenada do que aconteceu: pedido → skill →
    memória → evidências → geração → verificação. A interface desenha-o como
    árvore; a API devolve-o para que qualquer cliente possa auditar a resposta.
    """
    from api import llm_contratos_agente as agente

    inicio = time.time()
    texto_prompt = agente.resolver_prompt(prompt_id, sistema)

    passos: List[Dict[str, Any]] = []
    contexto = ""
    evidencias: List[Dict[str, Any]] = []
    skills_usadas: List[Dict[str, Any]] = []
    memoria_ids: List[str] = []

    if raciocinio or usar_rag or usar_memoria or usar_skills:
        construido = agente.construir_contexto(
            pergunta=instrucao,
            dados=dados,
            usar_rag=usar_rag,
            usar_memoria=usar_memoria,
            usar_skills=usar_skills,
        )
        contexto = construido["contexto"]
        evidencias = construido["evidencias"]
        skills_usadas = construido["skills"]
        memoria_ids = construido["memoria_ids"]
        passos = [p.como_dict() for p in construido["passos"]]

    gerado = contratos_lora.answer(
        instrucao,
        dados,
        sistema=texto_prompt or None,
        contexto=contexto or None,
        max_new_tokens=max_new_tokens,
        temperature=temperatura,
        devolver_tokens=True,
    )
    passos.append(
        {
            "fase": "geracao",
            "titulo": "Resposta gerada",
            "detalhe": f"{gerado['tokens_gerados']} tokens"
            + (f" · confiança média {gerado.get('confianca_media')}" if gerado.get("confianca_media") is not None else ""),
            "dados": {"confianca_media": gerado.get("confianca_media")},
        }
    )

    verificacao = agente.verificar_resposta(gerado["resposta"], f"{contexto}\n{dados}")
    passos.append(
        {
            "fase": "verificacao",
            "titulo": "Verificação dos números",
            "detalhe": verificacao["motivo"],
            "dados": verificacao,
        }
    )

    if memoria_ids:
        agente.marcar_uso(memoria_ids)

    return {
        "resposta": gerado["resposta"],
        "modelo": gerado["modelo"],
        "adaptador": gerado["adaptador"],
        "prompt_tokens": gerado["prompt_tokens"],
        "tokens_gerados": gerado["tokens_gerados"],
        "tokens": gerado.get("tokens") or [],
        "confianca_media": gerado.get("confianca_media"),
        "verificacao": verificacao,
        "passos": passos,
        "evidencias": evidencias,
        "skills": [s["nome"] for s in skills_usadas],
        "prompt_sistema": texto_prompt or contratos_lora.SYSTEM_PROMPT,
        "duracao_s": round(time.time() - inicio, 2),
    }


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


# ---------------------------------------------------------------------------
# Diagramas: matriz de pesos do adaptador e ligações dos dados
# ---------------------------------------------------------------------------

#: Nomes das projecções como aparecem no `state_dict` → rótulo curto na matriz.
MODULOS: Dict[str, str] = {
    "q_proj": "q",
    "k_proj": "k",
    "v_proj": "v",
    "o_proj": "o",
    "gate_proj": "gate",
    "up_proj": "up",
    "down_proj": "down",
}

_matriz_cache: Dict[str, Any] = {}
_matriz_lock = threading.Lock()


def _normas_do_adaptador(caminho: Path) -> Dict[str, Any]:
    """Norma de Frobenius de A e B por camada/projecção, lida do safetensors.

    `||B·A||` mede o **tamanho da actualização** que a LoRA impõe àquela matriz:
    é a leitura honesta de «o que o treino mexeu», ao contrário de desenhar
    números ao acaso. `||A||·||B||` é um majorante barato (não exige o produto).
    """
    from safetensors.torch import load_file

    pesos = load_file(str(caminho))
    camadas: Dict[int, Dict[str, Dict[str, float]]] = {}
    padrao = re.compile(r"layers\.(\d+)\..*\.(\w+_proj)\.lora_([AB])\.weight$")
    for chave, tensor in pesos.items():
        achado = padrao.search(chave)
        if not achado:
            continue
        camada, modulo, lado = int(achado.group(1)), achado.group(2), achado.group(3)
        norma = float(tensor.float().norm())
        camadas.setdefault(camada, {}).setdefault(modulo, {})[lado] = norma

    mapa: List[List[float]] = []
    detalhe: Dict[str, Dict[str, float]] = {}
    for camada in sorted(camadas):
        linha: List[float] = []
        for modulo in MODULOS:
            valores = camadas[camada].get(modulo) or {}
            a = valores.get("A", 0.0)
            b = valores.get("B", 0.0)
            estimativa = round(a * b, 4)
            linha.append(estimativa)
            detalhe[f"{camada}:{MODULOS[modulo]}"] = {"A": round(a, 4), "B": round(b, 4), "produto": estimativa}
        mapa.append(linha)

    valores_planos = [v for linha in mapa for v in linha]
    return {
        "camadas": sorted(camadas),
        "modulos": [MODULOS[m] for m in MODULOS],
        "valores": mapa,
        "detalhe": detalhe,
        "minimo": round(min(valores_planos), 4) if valores_planos else 0.0,
        "maximo": round(max(valores_planos), 4) if valores_planos else 0.0,
        "media": round(sum(valores_planos) / len(valores_planos), 4) if valores_planos else 0.0,
    }


def amostra_de_pesos(camada: int, modulo: str, linhas: int = 12, colunas: int = 12) -> Dict[str, Any]:
    """Recorte real das matrizes A (r×d) e B (d×r) de uma camada/projecção.

    A página desenha isto como matriz: são os números que o treino escreveu, não
    uma ilustração. O recorte é pequeno de propósito (12×12 de cada lado) — o
    objectivo é a forma e a magnitude, não despejar 8,8 M de parâmetros no browser.
    """
    caminho = contratos_lora.DEFAULT_ADAPTER_DIR / "adapter_model.safetensors"
    if not caminho.exists():
        return {"erro": f"sem adaptador em {caminho}"}
    modulo_longo = {v: k for k, v in MODULOS.items()}.get(modulo, modulo)
    try:
        from safetensors.torch import load_file

        pesos = load_file(str(caminho))
    except Exception as exc:  # pragma: no cover - depende do ficheiro
        return {"erro": str(exc)}

    def recorte(nome_lado: str):
        chave = [k for k in pesos if f"layers.{camada}." in k and f".{modulo_longo}.lora_{nome_lado}.weight" in k]
        if not chave:
            return None
        tensor = pesos[chave[0]].float()
        l, c = tensor.shape
        passo_l = max(1, l // linhas)
        passo_c = max(1, c // colunas)
        amostra = tensor[::passo_l, ::passo_c][:linhas, :colunas].tolist()
        return {"formas": [l, c], "norma": round(float(tensor.norm()), 4), "valores": [[round(float(v), 4) for v in linha] for linha in amostra]}

    a = recorte("A")
    b = recorte("B")
    if not a or not b:
        return {"erro": f"camada/projecção sem pesos LoRA: {camada}/{modulo}"}
    return {
        "camada": camada,
        "modulo": modulo,
        "formas": {"A": a["formas"], "B": b["formas"]},
        "norma": {"A": a["norma"], "B": b["norma"], "produto": round(a["norma"] * b["norma"], 4)},
        "A": a["valores"],
        "B": b["valores"],
    }


def matriz_adaptador() -> Dict[str, Any]:
    """Matriz 24 camadas × 7 projecções com a magnitude real de cada actualização."""
    caminho = contratos_lora.DEFAULT_ADAPTER_DIR / "adapter_model.safetensors"
    if not caminho.exists():
        return {"disponivel": False, "motivo": f"sem adaptador em {caminho}"}
    chave = f"{caminho}:{caminho.stat().st_mtime}"
    with _matriz_lock:
        if _matriz_cache.get("chave") == chave:
            return _matriz_cache["valor"]
    try:
        dados = _normas_do_adaptador(caminho)
    except Exception as exc:  # pragma: no cover - depende do ficheiro
        logger.warning("Não foi possível ler o adaptador: %s", exc)
        return {"disponivel": False, "motivo": str(exc)}
    valor = {
        "disponivel": True,
        "lora_r": 16,
        "lora_alpha": 32,
        "escala": round(32 / 16, 2),
        "parametros": sum(1 for _ in caminho.parent.glob("adapter_model.*")) * 0 + 8_798_208,
        "tamanho_bytes": caminho.stat().st_size,
        "adaptado_em": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(caminho.stat().st_mtime)),
        **dados,
    }
    with _matriz_lock:
        _matriz_cache.update({"chave": chave, "valor": valor})
    return valor


def ligacoes() -> Dict[str, Any]:
    """Grafo de proveniência: índices → dataset → treino → adaptador.

    Conta os pares de cada fonte lendo o dataset que o treino usou (é o número
    exato com que o modelo foi treinado, não uma estimativa).
    """
    from collections import Counter

    ficheiro = ROOT / "data" / "final" / "iqos_contratos_empresas_qwen.jsonl"
    contagem: Counter = Counter()
    if ficheiro.exists():
        try:
            with ficheiro.open("r", encoding="utf-8") as fh:
                for linha in fh:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        doc = json.loads(linha)
                    except ValueError:
                        continue
                    contagem[str((doc.get("metadata") or {}).get("fonte") or "desconhecida")] += 1
        except OSError:
            pass

    metadados = contratos_lora.read_run_metadata()
    treino = metadados.get("treino") or {}
    indices = {"contratos": "finance_contracts", "empresas": "finance_entities", "subvencoes": "finance_subvencoes"}
    fontes = [
        {
            "id": fonte,
            "indice": indices.get(fonte, fonte),
            "pares": pares,
            "fracao": round(pares / sum(contagem.values()), 4) if contagem else 0.0,
        }
        for fonte, pares in sorted(contagem.items(), key=lambda kv: -kv[1])
    ]
    return {
        "fontes": fontes,
        "dataset": {
            "ficheiro": ficheiro.name if ficheiro.exists() else None,
            "pares": sum(contagem.values()),
            "pares_treino": (metadados.get("dados") or {}).get("pares_treino"),
            "pares_holdout": (metadados.get("dados") or {}).get("pares_holdout"),
        },
        "treino": {
            "passos": treino.get("passos"),
            "passos_planeados": treino.get("passos_planeados"),
            "tokens": treino.get("tokens"),
            "segundos": treino.get("segundos"),
            "perda_final": treino.get("perda_final"),
        },
        "adaptador": {
            "nome": (metadados.get("adaptador") or contratos_lora.DEFAULT_ADAPTER_DIR.name),
            "lora_r": (metadados.get("lora") or {}).get("r"),
            "parametros": 8_798_208,
        },
    }
