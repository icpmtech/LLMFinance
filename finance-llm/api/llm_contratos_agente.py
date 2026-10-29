"""Agente do modelo de contratos: memória, skills, prompts, RAG, feedback e raciocínio.

O modelo afinado (ver `docs/modelo-contratos.md`) responde bem ao formato, mas
um 0,5 B não sabe o que não lhe foi ensinado nem guarda nada entre pedidos. Esta
camada é a **memória de trabalho** à volta dele:

- **Memória** (`finance_llm_memoria`, tipo `memoria`): factos que o utilizador
  ensina («a Câmara de Chaves é o Município de Chaves»), recuperados por
  relevância e injectados no prompt.
- **Skills** (`finance_llm_memoria`, tipo `skill`): duas famílias —
  *executáveis* (consultam o Elasticsearch por parâmetros: contratos de uma
  entidade, ficha de entidade, subsídios, totais) e *aprendidas* (instrução +
  exemplo guardado pelo utilizador, que passa a ser injectado como few-shot).
- **Prompts de sistema** (`finance_llm_prompts`): perfis prontos e editáveis
  (descrever, auditar, responder a cidadão…), escolhidos no chat/playground.
- **RAG** (`finance_llm_rag_chunks`): corpus de contratos/entidades/subsídios
  em pedaços, pesquisável por BM25 — a resposta passa a citar documentos reais.
- **Feedback** (`finance_llm_feedback`): cada resposta com avaliação e/ou
  correção humana; as correções são pares de treino (`pares_de_feedback`) que
  alimentam a **adaptação incremental** do adaptador LoRA
  (`api/llm_contratos_treino.py`).
- **Raciocínio** (`raciocinar`): um ciclo explícito e auditável —
  intenção → skill → evidências → rascunho → verificação dos números →
  resposta com passos e confiança.

Tudo degrada em silêncio quando o Elasticsearch não responde: o chat continua a
funcionar com o modelo, só perde memória, RAG e histórico.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from inference import contratos_eval

logger = logging.getLogger(__name__)

MEMORIA_INDEX = "finance_llm_memoria"
PROMPTS_INDEX = "finance_llm_prompts"
FEEDBACK_INDEX = "finance_llm_feedback"
RAG_INDEX = "finance_llm_rag_chunks"

_indices_ready = False
_indices_lock = threading.Lock()

MAPPINGS: Dict[str, Dict[str, Any]] = {
    MEMORIA_INDEX: {
        "properties": {
            "tipo": {"type": "keyword"},
            "titulo": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "instrucao": {"type": "text"},
            "dados": {"type": "text"},
            "resposta": {"type": "text"},
            "gatilhos": {"type": "keyword"},
            "origem": {"type": "keyword"},
            "usos": {"type": "integer"},
            "criado_em": {"type": "date"},
            "atualizado_em": {"type": "date"},
        }
    },
    PROMPTS_INDEX: {
        "properties": {
            "id": {"type": "keyword"},
            "nome": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "texto": {"type": "text"},
            "predefinido": {"type": "boolean"},
            "criado_em": {"type": "date"},
            "atualizado_em": {"type": "date"},
        }
    },
    FEEDBACK_INDEX: {
        "properties": {
            "instrucao": {"type": "text"},
            "dados": {"type": "text"},
            "resposta": {"type": "text"},
            "correcao": {"type": "text"},
            "nota": {"type": "integer"},
            "util": {"type": "boolean"},
            "skills": {"type": "keyword"},
            "usou_rag": {"type": "boolean"},
            "raciocinio": {"type": "boolean"},
            "utilizado": {"type": "boolean"},
            "criado_em": {"type": "date"},
        }
    },
    RAG_INDEX: {
        "properties": {
            "fonte": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "titulo": {"type": "text"},
            "texto": {"type": "text"},
            "metadata": {"type": "object", "enabled": False},
            "criado_em": {"type": "date"},
        }
    },
}

#: Prompts de sistema que a plataforma oferece de origem. O utilizador pode
#: editar/criar outros em `finance_llm_prompts` sem tocar no código.
PROMPTS_PREDEFINIDOS: List[Dict[str, str]] = [
    {
        "id": "descrever",
        "nome": "Descrever documento",
        # A instrução viaja com o perfil: o prompt de sistema sozinho não chega.
        # O modelo foi afinado com estas três instruções (ver
        # `training/export_es_dataset.py::_build_contrato_pt_variantes`); enviar
        # «Descreve este contrato» com o perfil «auditar» dava-lhe sinais
        # contrários e a resposta saía a descrever.
        "instrucao": "Descreve este contrato público português.",
        "texto": (
            "Assistente do IQ OS para contratos públicos, empresas e subsídios portugueses. "
            "Descreves o documento em 2-3 frases, só com os dados recebidos e as evidências. "
            "Se um campo faltar, dizes «não especificado»."
        ),
    },
    {
        "id": "auditar",
        "nome": "Auditar contrato",
        "instrucao": "Audita este contrato e aponta o que deve ser verificado.",
        "texto": (
            "Auditor de contratação pública. Identificas riscos objetivos (ajuste direto, valor "
            "elevado, prazo, concentração de fornecedor) usando apenas os dados e as evidências. "
            "Separas factos de interpretação e terminas com uma pergunta de verificação."
        ),
    },
    {
        "id": "cidadao",
        "nome": "Responder a cidadão",
        "instrucao": "Resume este contrato numa frase, para um cidadão.",
        "texto": (
            "Explicas contratos públicos a quem não é especialista: português simples, sem jargão, "
            "uma frase de contexto e os números que interessam. Nunca inventas valores."
        ),
    },
]

_TEXT_CACHE: Dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Elasticsearch (tolerante a falhas)
# ---------------------------------------------------------------------------


def _client():
    from api.elasticsearch_client import get_es_client

    return get_es_client()


def ensure_indices(es=None) -> bool:
    """Cria os índices do agente (idempotente)."""
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
            logger.warning("Não foi possível criar os índices do agente: %s", exc)
            return False


def _search(index: str, body: Dict[str, Any]) -> List[Dict[str, Any]]:
    client = _client()
    if not client or not ensure_indices(client):
        return []
    try:
        resposta = client.search(index=index, **body)
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Pesquisa em %s falhou: %s", index, exc)
        return []
    docs = []
    for hit in resposta.get("hits", {}).get("hits", []):
        doc = dict(hit.get("_source") or {})
        doc["id"] = hit.get("_id")
        doc["_score"] = hit.get("_score")
        docs.append(doc)
    return docs


def _index_doc(index: str, documento: Dict[str, Any], doc_id: Optional[str] = None) -> Optional[str]:
    client = _client()
    if not client or not ensure_indices(client):
        return None
    try:
        resp = client.index(index=index, id=doc_id, document=documento, refresh="wait_for")
        return resp.get("_id")
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Escrita em %s falhou: %s", index, exc)
        return None


def _delete_doc(index: str, doc_id: str) -> bool:
    client = _client()
    if not client:
        return False
    try:
        client.delete(index=index, id=doc_id, refresh="wait_for")
        return True
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Remoção em %s falhou: %s", index, exc)
        return False


# ---------------------------------------------------------------------------
# Memória e skills
# ---------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def guardar_memoria(
    *,
    tipo: str = "memoria",
    titulo: str,
    instrucao: str = "",
    dados: str = "",
    resposta: str = "",
    gatilhos: Optional[List[str]] = None,
    origem: str = "utilizador",
) -> Optional[str]:
    """Guarda um facto (`memoria`) ou uma skill aprendida (`skill`)."""
    tipo = "skill" if tipo == "skill" else "memoria"
    if not titulo.strip():
        raise ValueError("a memória precisa de um título")
    if tipo == "skill" and not (instrucao.strip() or resposta.strip()):
        raise ValueError("uma skill precisa de instrução ou de resposta de exemplo")
    doc = {
        "tipo": tipo,
        "titulo": titulo.strip()[:200],
        "instrucao": instrucao.strip()[:2000],
        "dados": dados.strip()[:4000],
        "resposta": resposta.strip()[:4000],
        "gatilhos": [g.lower() for g in (gatilhos or []) if g.strip()][:12],
        "origem": origem,
        "usos": 0,
        "criado_em": _now(),
        "atualizado_em": _now(),
    }
    return _index_doc(MEMORIA_INDEX, doc)


def listar_memorias(tipo: Optional[str] = None, size: int = 50) -> List[Dict[str, Any]]:
    """Lista memórias/skills. `tipo=None` devolve ambos."""
    query: Dict[str, Any] = {"match_all": {}} if not tipo else {"term": {"tipo": tipo}}
    return _search(MEMORIA_INDEX, {"query": query, "size": size, "sort": [{"criado_em": {"order": "desc"}}]})


def apagar_memoria(doc_id: str) -> bool:
    return _delete_doc(MEMORIA_INDEX, doc_id)


def recuperar_memorias(texto: str, k: int = 4) -> List[Dict[str, Any]]:
    """Memórias relevantes para um pedido (BM25 sobre título/instrução/dados).

    Um `should` com `match` + `term` nos gatilhos: um gatilho explícito vale mais
    do que uma coincidência de palavras, mas ambos contam.
    """
    texto = (texto or "").strip()
    if not texto:
        return []
    body = {
        "size": k,
        "query": {
            "bool": {
                "should": [
                    {"multi_match": {"query": texto, "fields": ["titulo^3", "instrucao^2", "dados", "resposta"]}},
                    {"terms": {"gatilhos": [t.lower() for t in re.findall(r"\w{4,}", texto)][:12]}},
                ],
                "minimum_should_match": 1,
            }
        },
    }
    return _search(MEMORIA_INDEX, body)


def marcar_uso(doc_ids: Iterable[str]) -> None:
    """Incrementa `usos` (best-effort; nunca falha o pedido por causa disto)."""
    client = _client()
    if not client:
        return
    for doc_id in doc_ids:
        try:
            client.update(index=MEMORIA_INDEX, id=doc_id, body={"script": {"source": "ctx._source.usos += 1"}})
        except Exception:  # pragma: no cover - depende do cluster
            continue


# ---------------------------------------------------------------------------
# Skills executáveis: consultam o Elasticsearch por parâmetros
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    """Uma capacidade que o agente sabe executar sem pedir nada ao modelo."""

    nome: str
    descricao: str
    gatilhos: Tuple[str, ...]
    executar: Callable[..., Dict[str, Any]]


def _resumo_contrato(item: Dict[str, Any]) -> Dict[str, Any]:
    adjudicantes = _nomes_de_parte(item.get("adjudicantes"))
    adjudicatarios = _nomes_de_parte(item.get("adjudicatarios"))
    return {
        "idcontrato": item.get("idcontrato"),
        "objeto": item.get("objectoContrato") or item.get("descContrato") or "",
        "preco": item.get("precoContratual"),
        "data": item.get("dataCelebracaoContrato") or item.get("dataPublicacao"),
        "adjudicante": adjudicantes[0] if adjudicantes else None,
        "adjudicatario": adjudicatarios[0] if adjudicatarios else None,
        "tipo": item.get("tipoContrato"),
        "procedimento": item.get("tipoprocedimento"),
    }


PALAVRAS_VAZIAS = {
    "quantos",
    "quantas",
    "quanto",
    "quanta",
    "contrato",
    "contratos",
    "tem",
    "têm",
    "qual",
    "quais",
    "maior",
    "menor",
    "total",
    "número",
    "numero",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "e",
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "em",
    "no",
    "na",
    "por",
    "para",
    "que",
    "com",
    "sobre",
    "me",
    "diz",
    "diga",
    "lista",
    "listar",
    "mostra",
    "mostrar",
    "ver",
}


def termos_uteis(pergunta: str) -> str:
    """Tira as palavras de pergunta e guarda o que identifica o documento.

    Sem isto, a skill de contagem ia procurar a frase inteira («quantos contratos
    tem o municipio de chaves e qual o maior») e o `total` vinha de um `match`
    frouxo — dava 22 milhões em vez dos contratos daquele município.
    """
    palavras = re.findall(r"[\wÀ-ÿ]{3,}", (pergunta or "").lower())
    return " ".join(p for p in palavras if _sem_acentos(p) not in PALAVRAS_VAZIAS)


def _skill_contratos(termo: str = "", entidade: str = "", limite: int = 4) -> Dict[str, Any]:
    """Contratos que casam com um termo ou pertencem a uma entidade."""
    from api.es.contratos import search_contracts

    termo = termos_uteis(termo) or termo
    resposta = search_contracts(q=termo or None, entity=entidade or None, size=limite, strict=True)
    itens = [_resumo_contrato(i) for i in (resposta.get("items") or [])[:limite]]
    return {"total": resposta.get("total"), "itens": itens}


def _skill_entidade(nome: str = "", nif: str = "") -> Dict[str, Any]:
    """Ficha resumida de uma entidade do cadastro."""
    from api.es.entidades import search_companies

    if nif:
        resposta = search_companies(nif=nif, size=1)
    else:
        resposta = search_companies(q=nome, size=1)
    itens = resposta.get("items") or []
    if not itens:
        return {"encontrado": False}
    e = itens[0]
    return {
        "encontrado": True,
        "nif": e.get("nif"),
        "nome": e.get("name"),
        "contratos": e.get("contracts_total"),
        "valor_total": e.get("total_value"),
        "adjudicante": e.get("adjudicante"),
        "adjudicatario": e.get("adjudicatario"),
        "cae": e.get("cae_principal"),
    }


def _skill_subsidios(beneficiario: str = "", limite: int = 4) -> Dict[str, Any]:
    """Subsídios atribuídos a um beneficiário (índice `finance_subvencoes`)."""
    from api.elasticsearch_client import SUBVENCOES_INDEX, get_es_client

    client = get_es_client()
    if not client:
        return {"erro": "Elasticsearch indisponível"}
    try:
        resposta = client.search(
            index=SUBVENCOES_INDEX,
            size=limite,
            query={"match": {"beneficiario": beneficiario}} if beneficiario else {"match_all": {}},
        )
    except Exception as exc:
        return {"erro": str(exc)}
    itens = []
    total = 0.0
    for hit in resposta.get("hits", {}).get("hits", []):
        doc = hit.get("_source") or {}
        try:
            total += float(doc.get("montante") or 0)
        except (TypeError, ValueError):
            pass
        itens.append(
            {
                "beneficiario": doc.get("beneficiario"),
                "entidade": doc.get("entidadeAtribuinte") or doc.get("entidade"),
                "montante": doc.get("montante"),
                "finalidade": doc.get("finalidade"),
                "data": doc.get("dataDecisao") or doc.get("data"),
            }
        )
    return {"total_montante": round(total, 2), "itens": itens}


def _skill_contagem(termo: str = "", entidade: str = "") -> Dict[str, Any]:
    """Quantos contratos casam com o termo/entidade (não devolve documentos)."""
    from api.es.contratos import search_contracts

    limpo = termos_uteis(termo) or termo
    resposta = search_contracts(q=limpo or None, entity=entidade or None, size=1, strict=True)
    return {"total": resposta.get("total"), "termo_pesquisado": limpo, "entidade": entidade}


SKILLS: Dict[str, Skill] = {
    "procurar_contratos": Skill(
        nome="procurar_contratos",
        descricao="Procura contratos por palavras (objeto, descrição) ou por entidade.",
        gatilhos=("contrato", "contratos", "adjudicante", "adjudicatario", "preco", "valor"),
        executar=_skill_contratos,
    ),
    "ficha_entidade": Skill(
        nome="ficha_entidade",
        descricao="Devolve a ficha de uma entidade: NIF, contratos, valor total e papel.",
        gatilhos=("entidade", "empresa", "nif", "fornecedor", "adjudicatario", "quem"),
        executar=_skill_entidade,
    ),
    "subsidios": Skill(
        nome="subsidios",
        descricao="Procura subsídios de um beneficiário e soma os montantes.",
        gatilhos=("subsidio", "subsidios", "beneficiario", "apoio", "financiamento", "montante"),
        executar=_skill_subsidios,
    ),
    "contagem": Skill(
        nome="contagem",
        descricao="Conta contratos que casam com um termo ou entidade.",
        gatilhos=("quantos", "quantas", "numero", "total de contratos"),
        executar=_skill_contagem,
    ),
}


def skills_disponiveis() -> List[Dict[str, Any]]:
    """Catálogo das skills executáveis (para a interface e para o prompt)."""
    return [
        {"nome": s.nome, "descricao": s.descricao, "gatilhos": list(s.gatilhos), "tipo": "executavel"}
        for s in SKILLS.values()
    ]


def _sem_acentos(texto: str) -> str:
    """Minúsculas e sem acentos — para comparar gatilhos com o que o utilizador escreve.

    «subsidio» (gatilho) tem de casar com «subsídios» (pergunta); sem isto, metade
    das skills nunca disparava em português.
    """
    decomposto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def escolher_skills(pergunta: str, maximo: int = 2) -> List[str]:
    """Escolhe skills por gatilho (determinístico, barato e explicável).

    Não se usa o modelo para escolher: um 0,5 B a decidir ferramentas erra mais
    do que uma lista de gatilhos, e o utilizador tem de conseguir perceber
    porque é que uma skill correu (aparece no traço da resposta).
    """
    texto = _sem_acentos(pergunta)
    pontuacao: List[Tuple[int, str]] = []
    for skill in SKILLS.values():
        acertos = sum(1 for g in skill.gatilhos if _sem_acentos(g) in texto)
        if acertos:
            pontuacao.append((acertos, skill.nome))
    pontuacao.sort(reverse=True)
    return [nome for _, nome in pontuacao[:maximo]]


def executar_skill(nome: str, pergunta: str) -> Dict[str, Any]:
    """Corre uma skill, extraindo os parâmetros da própria pergunta."""
    skill = SKILLS.get(nome)
    if not skill:
        return {"erro": f"skill desconhecida: {nome}"}
    nif = re.search(r"\b(\d{9})\b", pergunta or "")
    if nome == "ficha_entidade":
        return skill.executar(nif=nif.group(1) if nif else "", nome="" if nif else (pergunta or "")[:120])
    if nome == "subsidios":
        return skill.executar(beneficiario=(pergunta or "")[:120])
    if nome == "contagem":
        return skill.executar(termo=(pergunta or "")[:120])
    return skill.executar(termo=(pergunta or "")[:120], limite=4)


# ---------------------------------------------------------------------------
# Prompts de sistema
# ---------------------------------------------------------------------------


def listar_prompts() -> List[Dict[str, Any]]:
    """Prompts predefinidos + os guardados pelo utilizador."""
    guardados = _search(PROMPTS_INDEX, {"size": 100, "query": {"match_all": {}}, "sort": [{"atualizado_em": {"order": "desc"}}]})
    vistos = {p["id"] for p in guardados}
    lista = list(guardados)
    for predef in PROMPTS_PREDEFINIDOS:
        if predef["id"] not in vistos:
            lista.append({**predef, "predefinido": True})
    return lista


def guardar_prompt(*, prompt_id: str, nome: str, texto: str) -> Optional[str]:
    if not texto.strip():
        raise ValueError("o prompt não pode estar vazio")
    slug = re.sub(r"[^a-z0-9-]+", "-", (prompt_id or nome).strip().lower()).strip("-")[:60] or "prompt"
    return _index_doc(
        PROMPTS_INDEX,
        {
            "id": slug,
            "nome": nome.strip()[:120] or slug,
            "texto": texto.strip()[:6000],
            "predefinido": False,
            "criado_em": _now(),
            "atualizado_em": _now(),
        },
        doc_id=slug,
    )


def apagar_prompt(prompt_id: str) -> bool:
    return _delete_doc(PROMPTS_INDEX, prompt_id)


def resolver_prompt(prompt_id: Optional[str], sistema: Optional[str]) -> str:
    """Texto do prompt escolhido (sistema explícito ganha ao id)."""
    if sistema and sistema.strip():
        return sistema.strip()[:6000]
    if prompt_id:
        for predef in PROMPTS_PREDEFINIDOS:
            if predef["id"] == prompt_id:
                return predef["texto"]
        docs = _search(PROMPTS_INDEX, {"size": 1, "query": {"term": {"id": prompt_id}}})
        if docs:
            return str(docs[0].get("texto") or "")
    return ""


# ---------------------------------------------------------------------------
# RAG: corpus de pedaços pesquisáveis + recuperação
# ---------------------------------------------------------------------------


def _nomes_de_parte(campo: Any) -> List[str]:
    """Nomes de uma parte do contrato, seja qual for a forma do campo.

    No índice, `adjudicantes` é um objeto (`{"raw": [...], "parsed": [{"nome": …}]}`);
    na pesquisa de alto nível (`search_contracts`) os itens já trazem listas. Um
    `KeyError: 0` a meio da indexação do RAG vinha exatamente desta diferença.
    """
    if isinstance(campo, str):
        return [campo] if campo.strip() else []
    if isinstance(campo, list):
        nomes = []
        for item in campo:
            if isinstance(item, str):
                nomes.append(item)
            elif isinstance(item, dict) and item.get("nome"):
                nomes.append(str(item["nome"]))
        return nomes
    if isinstance(campo, dict):
        parsed = campo.get("parsed")
        if isinstance(parsed, list):
            return [str(p["nome"]) for p in parsed if isinstance(p, dict) and p.get("nome")]
        raw = campo.get("raw")
        if isinstance(raw, list):
            return [re.sub(r"^\d{9}\s*-\s*", "", str(r)) for r in raw]
    return []


def _chunk_de_contrato(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    objeto = doc.get("objectoContrato") or doc.get("descContrato") or ""
    nomes_adq = _nomes_de_parte(doc.get("adjudicantes"))
    nomes_atr = _nomes_de_parte(doc.get("adjudicatarios"))
    nome_adq = nomes_adq[0] if nomes_adq else ""
    nome_atr = nomes_atr[0] if nomes_atr else ""
    if not (objeto or nome_adq):
        return None
    texto = (
        f"Contrato {doc.get('idcontrato')} — {objeto}. "
        f"Adjudicante: {nome_adq or 'não especificado'}. "
        f"Adjudicatário: {nome_atr or 'não especificado'}. "
        f"Preço: {doc.get('precoContratual')}. "
        f"Data: {doc.get('dataCelebracaoContrato') or doc.get('dataPublicacao')}. "
        f"Procedimento: {doc.get('tipoprocedimento')}."
    )
    return {
        "fonte": "contratos",
        "doc_id": str(doc.get("idcontrato")),
        "titulo": objeto[:200] or f"Contrato {doc.get('idcontrato')}",
        "texto": texto,
        "metadata": {"adjudicante": nome_adq, "adjudicatario": nome_atr, "preco": doc.get("precoContratual")},
    }


def _chunk_de_entidade(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    nome = doc.get("name") or doc.get("nome")
    if not nome:
        return None
    texto = (
        f"Entidade {nome} (NIF {doc.get('nif') or 'não especificado'}). "
        f"Contratos: {doc.get('contracts_total')}. Valor total: {doc.get('total_value')}. "
        f"Papel: adjudicante={doc.get('adjudicante')}, adjudicatário={doc.get('adjudicatario')}."
    )
    return {
        "fonte": "empresas",
        "doc_id": str(doc.get("nif") or nome),
        "titulo": nome[:200],
        "texto": texto,
        "metadata": {"nif": doc.get("nif")},
    }


def _chunk_de_subvencao(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    benef = doc.get("beneficiario")
    if not benef:
        return None
    texto = (
        f"Subsídio a {benef}, atribuído por {doc.get('entidadeAtribuinte') or doc.get('entidade') or 'não especificado'}, "
        f"montante {doc.get('montante')}, finalidade {doc.get('finalidade') or 'não especificada'}, "
        f"data {doc.get('dataDecisao') or doc.get('data') or 'não especificada'}."
    )
    return {
        "fonte": "subvencoes",
        "doc_id": str(doc.get("id") or doc.get("nif") or benef),
        "titulo": f"Subsídio a {benef}"[:200],
        "texto": texto,
        "metadata": {"montante": doc.get("montante")},
    }


_RECOLHAS: Dict[str, Tuple[str, Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]]] = {
    "contratos": ("finance_contracts", _chunk_de_contrato),
    "empresas": ("finance_entities", _chunk_de_entidade),
    "subvencoes": ("finance_subvencoes", _chunk_de_subvencao),
}


def indexar_rag(max_por_fonte: int = 400, fontes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Constrói o corpus RAG a partir dos índices do IQ OS.

    Escreve em `finance_llm_rag_chunks` (idempotente por `fonte:doc_id`). Usa os
    mesmos `_source` que o exportador de treino (`training/export_es_dataset.py`),
    para que a memória e o modelo falem dos mesmos documentos.
    """
    client = _client()
    if not client or not ensure_indices(client):
        return {"erro": "Elasticsearch indisponível"}
    resultado: Dict[str, Any] = {"fontes": {}, "total": 0}
    for fonte, (indice, transformar) in _RECOLHAS.items():
        if fontes and fonte not in fontes:
            continue
        escrito = 0
        saltado = 0
        try:
            resposta = client.search(index=indice, size=max(1, min(max_por_fonte, 2000)), query={"match_all": {}})
            hits = resposta.get("hits", {}).get("hits", [])
        except Exception as exc:
            resultado["fontes"][fonte] = {"erro": str(exc)}
            continue
        for hit in hits:
            chunk = transformar(hit.get("_source") or {})
            if not chunk:
                saltado += 1
                continue
            doc_id = f"{fonte}:{chunk['doc_id']}"
            if _index_doc(RAG_INDEX, {**chunk, "criado_em": _now()}, doc_id=doc_id):
                escrito += 1
        resultado["fontes"][fonte] = {"indice": indice, "lidos": len(hits), "escritos": escrito, "saltados": saltado}
        resultado["total"] += escrito
    resultado["concluido_em"] = _now()
    return resultado


def recuperar_rag(pergunta: str, k: int = 4) -> List[Dict[str, Any]]:
    """Pedaços mais relevantes para uma pergunta (BM25 sobre `texto`)."""
    if not (pergunta or "").strip():
        return []
    docs = _search(
        RAG_INDEX,
        {
            "size": k,
            "query": {
                "multi_match": {
                    "query": pergunta,
                    "fields": ["titulo^2", "texto"],
                    "type": "best_fields",
                }
            },
        },
    )
    return docs


def estado_rag() -> Dict[str, Any]:
    client = _client()
    if not client or not ensure_indices(client):
        return {"disponivel": False, "documentos": 0}
    try:
        total = int(client.count(index=RAG_INDEX).get("count", 0))
        return {"disponivel": True, "documentos": total, "indice": RAG_INDEX}
    except Exception as exc:  # pragma: no cover - depende do cluster
        return {"disponivel": False, "documentos": 0, "erro": str(exc)}


# ---------------------------------------------------------------------------
# Feedback e auto-aprendizagem
# ---------------------------------------------------------------------------


def guardar_feedback(
    *,
    instrucao: str,
    dados: str,
    resposta: str,
    correcao: str = "",
    nota: int = 0,
    skill: Optional[List[str]] = None,
    usou_rag: bool = False,
    raciocinio: bool = False,
) -> Optional[str]:
    """Guarda uma avaliação (e a correção, se houver) de uma resposta do modelo."""
    util = nota > 0
    return _index_doc(
        FEEDBACK_INDEX,
        {
            "instrucao": (instrucao or "")[:2000],
            "dados": (dados or "")[:6000],
            "resposta": (resposta or "")[:6000],
            "correcao": (correcao or "")[:6000],
            "nota": int(nota),
            "util": util,
            "skills": skill or [],
            "usou_rag": bool(usou_rag),
            "raciocinio": bool(raciocinio),
            "utilizado": False,
            "criado_em": _now(),
        },
    )


def estatisticas_feedback() -> Dict[str, Any]:
    docs = _search(FEEDBACK_INDEX, {"size": 500, "query": {"match_all": {}}})
    corrigidos = [d for d in docs if (d.get("correcao") or "").strip()]
    return {
        "total": len(docs),
        "uteis": sum(1 for d in docs if d.get("util")),
        "corrigidos": len(corrigidos),
        "por_utilizar": sum(1 for d in corrigidos if not d.get("utilizado")),
        "nota_media": round(sum(int(d.get("nota") or 0) for d in docs) / len(docs), 2) if docs else None,
    }


def pares_de_feedback(limite: int = 200, apenas_novos: bool = True) -> List[Dict[str, Any]]:
    """Converte correções humanas em pares Alpaca (a matéria-prima do retreino)."""
    query: Dict[str, Any] = {"exists": {"field": "correcao"}}
    docs = _search(
        FEEDBACK_INDEX,
        {"size": min(limite, 500), "query": query, "sort": [{"criado_em": {"order": "asc"}}]},
    )
    pares: List[Dict[str, Any]] = []
    for doc in docs:
        correcao = (doc.get("correcao") or "").strip()
        if not correcao:
            continue
        if apenas_novos and doc.get("utilizado"):
            continue
        pares.append(
            {
                "instruction": doc.get("instrucao") or "Descreve este documento.",
                "input": doc.get("dados") or "",
                "output": correcao,
                "metadata": {"fonte": "feedback", "feedback_id": doc.get("id"), "nota": doc.get("nota")},
            }
        )
    pares.extend(_pares_de_skills())
    return pares


def _pares_de_skills() -> List[Dict[str, Any]]:
    """Skills guardadas com resposta de exemplo também são pares de treino."""
    pares = []
    for doc in listar_memorias(tipo="skill", size=100):
        if (doc.get("resposta") or "").strip() and (doc.get("dados") or "").strip():
            pares.append(
                {
                    "instruction": doc.get("instrucao") or doc.get("titulo"),
                    "input": doc.get("dados"),
                    "output": doc.get("resposta"),
                    "metadata": {"fonte": "skill", "skill": doc.get("titulo")},
                }
            )
    return pares


def marcar_feedback_utilizado(feedback_ids: Iterable[str]) -> None:
    client = _client()
    if not client:
        return
    for doc_id in feedback_ids:
        try:
            client.update(index=FEEDBACK_INDEX, id=doc_id, body={"doc": {"utilizado": True}})
        except Exception:  # pragma: no cover - depende do cluster
            continue


# ---------------------------------------------------------------------------
# Raciocínio: intenção → skill → evidências → rascunho → verificação
# ---------------------------------------------------------------------------


@dataclass
class Passo:
    """Um passo do traço de raciocínio (o que a interface desenha em árvore)."""

    fase: str
    titulo: str
    detalhe: str = ""
    dados: Dict[str, Any] = field(default_factory=dict)

    def como_dict(self) -> Dict[str, Any]:
        return {"fase": self.fase, "titulo": self.titulo, "detalhe": self.detalhe, "dados": self.dados}


def _pergunta_aberta(pergunta: str) -> bool:
    """A instrução é uma pergunta (precisa de ir além do documento)?

    «Descreve este contrato» descreve-se com o documento à frente; «quanto
    custou o contrato X?» precisa de ir buscar o contrato. Sem esta distinção, o
    RAG injectava pedaços de outros documentos e o modelo de 0,5 B misturava-os:
    um contrato de Condeixa-a-Nova saía com o montante de um subsídio e com o
    adjudicatário de um contrato de arquivo (visto no chat).
    """
    texto = (pergunta or "").strip().lower()
    if not texto:
        return False
    if "?" in texto:
        return True
    return any(
        palavra in texto.split()
        for palavra in ("quanto", "quem", "qual", "quais", "quantos", "quantas", "onde", "quando")
    )


def construir_contexto(
    *,
    pergunta: str,
    dados: str = "",
    usar_rag: bool = True,
    usar_memoria: bool = True,
    usar_skills: bool = True,
    k_rag: int = 3,
    k_memoria: int = 3,
) -> Dict[str, Any]:
    """Junta memória, base de conhecimento (RAG) e resultados de skills.

    Devolve também o traço: cada fonte entra como um passo, com o que contribuiu.
    É isto que transforma «o modelo respondeu» em «o modelo respondeu porque».
    """
    passos: List[Passo] = [Passo("pergunta", "Pedido recebido", (pergunta or "")[:180])]
    partes: List[str] = []
    evidencias: List[Dict[str, Any]] = []
    skills_usadas: List[Dict[str, Any]] = []
    memoria_ids: List[str] = []

    if usar_skills:
        for nome in escolher_skills(pergunta):
            try:
                resultado = executar_skill(nome, pergunta)
            except Exception as exc:  # uma skill nunca derruba o pedido
                resultado = {"erro": str(exc)}
            skills_usadas.append({"nome": nome, "resultado": resultado})
            passos.append(
                Passo(
                    "skill",
                    f"Skill `{nome}`",
                    SKILLS[nome].descricao,
                    {"resultado": resultado},
                )
            )
            partes.append(f"[SKILL {nome}] {json.dumps(resultado, ensure_ascii=False, default=str)[:2000]}")

    if usar_memoria:
        memorias = recuperar_memorias(f"{pergunta}\n{dados[:400]}", k=k_memoria)
        if memorias:
            memoria_ids = [m["id"] for m in memorias if m.get("id")]
            linhas = []
            for m in memorias:
                rotulo = "SKILL APRENDIDA" if m.get("tipo") == "skill" else "MEMÓRIA"
                extra = f" (exemplo: {m['resposta'][:200]})" if m.get("resposta") else ""
                linhas.append(f"- [{rotulo}] {m.get('titulo')}: {m.get('instrucao') or m.get('dados')}{extra}")
            partes.append("[MEMÓRIA]\n" + "\n".join(linhas))
            passos.append(Passo("memoria", f"{len(memorias)} memórias relevantes", "\n".join(linhas)[:500]))

    if usar_rag:
        # Pesquisar com o **documento**, não com a instrução. «Descreve este
        # contrato público português» não tem termos de contrato nenhum: o BM25
        # devolvia o que calhava (num teste real, um contrato de Condeixa-a-Nova
        # veio com o montante de um subsídio da Segurança Social colado à
        # resposta). O início do documento é o que identifica o objeto.
        consulta_rag = (dados.strip()[:400] or pergunta).strip()
        chunks = recuperar_rag(consulta_rag, k=k_rag)
        if chunks:
            evidencias = [
                {
                    "fonte": c.get("fonte"),
                    "titulo": c.get("titulo"),
                    "texto": (c.get("texto") or "")[:600],
                    "doc_id": c.get("doc_id"),
                }
                for c in chunks
            ]
            partes.append("[EVIDÊNCIAS]\n" + "\n".join(f"- ({e['fonte']}) {e['texto']}" for e in evidencias))
            passos.append(
                Passo("rag", f"{len(evidencias)} evidências recuperadas", f"índice {RAG_INDEX}", {"evidencias": evidencias})
            )

    if dados.strip():
        partes.append(f"[DADOS DO PEDIDO]\n{dados.strip()[:4000]}")
        passos.append(Passo("dados", "Documento do pedido", dados.strip()[:200]))

    return {
        "contexto": "\n\n".join(partes),
        "passos": passos,
        "evidencias": evidencias,
        "skills": skills_usadas,
        "memoria_ids": memoria_ids,
    }


def verificar_resposta(resposta: str, contexto: str) -> Dict[str, Any]:
    """Confere se os números da resposta aparecem no contexto (anti-alucinação).

    Um modelo pequeno troca valores com facilidade; a verificação é barata e
    diz ao utilizador (e à interface) se a resposta é sustentada.
    """
    numeros_resposta = set(contratos_eval.numeric_tokens(resposta))
    numeros_contexto = set(contratos_eval.numeric_tokens(contexto))
    if not numeros_resposta:
        return {"suportados": [], "inventados": [], "confianca": 0.5, "motivo": "resposta sem números"}
    suportados = sorted(n for n in numeros_resposta if n in numeros_contexto)
    inventados = sorted(n for n in numeros_resposta if n not in numeros_contexto)
    confianca = round(len(suportados) / len(numeros_resposta), 3)
    return {
        "suportados": suportados,
        "inventados": inventados,
        "confianca": confianca,
        "motivo": "todos os números vêm do contexto" if not inventados else "há números sem suporte no contexto",
    }
