"""Analogias: os contratos semelhantes do mercado para os contratos de uma resposta.

Fica em ficheiro próprio (e não no `deep_search_analysis`) porque é a peça que
fala com o Elasticsearch de vectores e a que mais falha: interessa poder testá-la
isolada.

Duas formas de encontrar os semelhantes, por esta ordem:

1. **Semântica** — o `embedding` do próprio contrato já está indexado (foi o
   backfill que o pôs lá), portanto a vizinhança faz-se com um kNN a partir do
   vector do documento, e não do vector de uma pergunta. É isto que responde a
   «contratos como este».
2. **Mesmo CPV e faixa de valor** — funciona sempre, mesmo com cobertura de
   vectores baixa (o backfill ainda vai a caminho). Sem ela, uma resposta sobre
   contratos sem vector ficava sem um único semelhante.

Em qualquer dos casos o resultado diz **porquê** (`porque`), para a página poder
mostrar a razão em vez de um número sem explicação.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import deep_search_service as deep
from api import search_service
from api import vector_service as vectors

logger = logging.getLogger(__name__)

#: Quantos contratos da resposta se comparam e quantos semelhantes cada um traz.
CONTRATOS_PADRAO = 3
SEMELHANTES_PADRAO = 3
SEMELHANTES_MAX = 8

#: Sem vector, aceita-se um contrato do mesmo CPV cujo valor esteja nesta banda
#: (±50 %) do valor do contrato em causa.
BANDA_VALOR = 0.5
#: Candidatos por consulta kNN (o `num_candidates` do Elasticsearch).
FATOR_CANDIDATOS = 6
TIMEOUT = 12.0

#: Campos que é preciso ler do contrato alvo: o vector e os dados que a página
#: mostra em cada semelhante.
_CAMPOS_ALVO = [
    "embedding",
    "objectoContrato",
    "descContrato",
    "precoContratual",
    "cpv",
    "Ano",
    "idcontrato",
    "adjudicantes",
    "adjudicatarios",
]
_CAMPOS_SEMELHANTE = [
    "idcontrato",
    "objectoContrato",
    "descContrato",
    "precoContratual",
    "cpv",
    "Ano",
    "adjudicantes",
    "adjudicatarios",
]


def _euros(valor: Any) -> str:
    """Valor em euros legível (reutiliza o formatador da pesquisa profunda)."""
    return deep._euros(valor)


def _primeiro_cpv(valor: Any) -> Optional[str]:
    codigo = search_service._cpv_code(valor)
    return str(codigo).strip() if codigo else None


def _nome_da_parte(partes: Any) -> str:
    nomes = search_service._party_names(partes)
    return nomes[0] if nomes else ""


def _resumo_do_contrato(origem: Dict[str, Any], *, score: Optional[float] = None) -> Dict[str, Any]:
    """Contrato no formato que a página desenha (id, título, valor, CPV, partes)."""
    idcontrato = str(origem.get("idcontrato") or origem.get("doc_id") or "").strip()
    return {
        "id": idcontrato,
        "title": str(origem.get("objectoContrato") or origem.get("descContrato") or "Contrato").strip(),
        "preco": _euros(origem.get("precoContratual")),
        "preco_valor": float(origem.get("precoContratual") or 0.0),
        "cpv": _primeiro_cpv(origem.get("cpv")),
        "ano": origem.get("Ano"),
        "adjudicante": _nome_da_parte(origem.get("adjudicantes")),
        "adjudicatario": _nome_da_parte(origem.get("adjudicatarios")),
        "score": round(float(score), 4) if isinstance(score, (int, float)) else None,
    }


def _ler_alvo(idcontrato: str) -> Optional[Dict[str, Any]]:
    """Lê o contrato alvo, incluindo o `embedding` (é o que permite o kNN).

    Procura-se pelo campo `idcontrato` e só em alternativa pelo `_id`: o `_id`
    do documento nem sempre é o número do contrato (depende de como o documento
    entrou no índice), e era isso que fazia só um de cada três contratos ser
    encontrado.
    """
    es = search_service.get_es_client()
    if es is None:
        return None
    for consulta in (
        {"term": {"idcontrato": str(idcontrato)}},
        {"ids": {"values": [str(idcontrato)]}},
    ):
        try:
            resposta = es.search(
                index=vectors.CONTRACTS_INDEX,
                body={"size": 1, "query": consulta, "_source": list(_CAMPOS_ALVO)},
                request_timeout=TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 - sem o alvo não há analogia
            logger.debug("Analogias: leitura do contrato %s falhou: %s", idcontrato, exc)
            continue
        hits = ((resposta.get("hits") or {}).get("hits") or []) if resposta else []
        if not hits:
            continue
        origem = dict(hits[0].get("_source") or {})
        origem.setdefault("idcontrato", idcontrato)
        origem["doc_id"] = hits[0].get("_id")
        return origem
    return None


def _excluir_alvo(alvo: Dict[str, Any]) -> Dict[str, Any]:
    """Filtro que tira o próprio contrato dos resultados (não é semelhante a si)."""
    valores = [
        valor
        for valor in (str(alvo.get("doc_id") or "").strip(), str(alvo.get("idcontrato") or "").strip())
        if valor
    ]
    if not valores:
        return {}
    return {"bool": {"must_not": [{"ids": {"values": list(dict.fromkeys(valores))}}]}}


def _vizinhos_semanticos(alvo: Dict[str, Any], quantos: int) -> List[Dict[str, Any]]:
    """Contratos mais próximos do **vector** do contrato alvo (kNN)."""
    vetor = alvo.get("embedding")
    if not isinstance(vetor, (list, tuple)) or not vetor:
        return []
    es = search_service.get_es_client()
    if es is None:
        return []
    corpo: Dict[str, Any] = {
        "size": quantos,
        "_source": list(_CAMPOS_SEMELHANTE),
        "knn": {
            "field": "embedding",
            "query_vector": list(vetor),
            "k": quantos,
            "num_candidates": max(50, quantos * FATOR_CANDIDATOS),
        },
    }
    exclusao = _excluir_alvo(alvo)
    if exclusao:
        # O próprio contrato é sempre o vizinho mais próximo: fica de fora.
        corpo["knn"]["filter"] = exclusao
    try:
        resposta = es.search(index=vectors.CONTRACTS_INDEX, body=corpo, request_timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - cai na alternativa por CPV/valor
        logger.debug("Analogias: kNN do contrato %s falhou: %s", alvo.get("idcontrato"), exc)
        return []
    return [
        _resumo_do_contrato(dict(hit.get("_source") or {}), score=hit.get("_score"))
        for hit in ((resposta.get("hits") or {}).get("hits") or [])
    ]


def _vizinhos_por_cpv_e_valor(alvo: Dict[str, Any], quantos: int) -> List[Dict[str, Any]]:
    """Alternativa que funciona sempre: mesmo CPV e valor na mesma banda.

    É o caminho de quem ainda não tem vector (a cobertura do backfill é parcial)
    e serve de rede de segurança quando o kNN devolve pouca coisa.
    """
    cpv = _primeiro_cpv(alvo.get("cpv"))
    valor = float(alvo.get("precoContratual") or 0.0)
    if not cpv or valor <= 0:
        return []
    es = search_service.get_es_client()
    if es is None:
        return []
    filtros: List[Dict[str, Any]] = [
        {"nested": {"path": "cpv", "query": {"term": {"cpv.code": cpv}}}},
        {"range": {"precoContratual": {"gte": valor * (1 - BANDA_VALOR), "lte": valor * (1 + BANDA_VALOR)}}},
    ]
    exclusao = _excluir_alvo(alvo)
    if exclusao:
        filtros.append(exclusao)
    try:
        resposta = es.search(
            index=vectors.CONTRACTS_INDEX,
            body={
                "size": quantos,
                "query": {"bool": {"filter": filtros}},
                # Por valor mais próximo do alvo (a banda já limita o desvio).
                "sort": [{"precoContratual": {"order": "asc"}}],
                "_source": list(_CAMPOS_SEMELHANTE),
            },
            request_timeout=TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Analogias: alternativa por CPV/valor falhou para %s: %s", alvo.get("idcontrato"), exc)
        return []
    return [
        _resumo_do_contrato(dict(hit.get("_source") or {}))
        for hit in ((resposta.get("hits") or {}).get("hits") or [])
    ]


def _posicao_no_mercado(valor: float, referencia: Dict[str, Any]) -> Dict[str, Any]:
    """Onde cai o valor face à mediana/p75 do mesmo CPV."""
    def numero(texto: Any) -> float:
        return float(str(texto or "0").replace("€", "").replace(" ", "").replace(".", "").replace(",", ".") or 0)

    mediana = numero(referencia.get("mediana"))
    p25 = numero(referencia.get("p25"))
    p75 = numero(referencia.get("p75"))
    if not mediana or valor <= 0:
        return {"estado": "desconhecido", "frase": "Sem referência de mercado para este CPV."}
    if valor > p75:
        estado, frase = "acima", "acima do p75 do mesmo CPV"
    elif valor < p25:
        estado, frase = "abaixo", "abaixo do p25 do mesmo CPV"
    else:
        estado, frase = "dentro", "dentro da metade central do mesmo CPV"
    vezes = valor / mediana
    return {
        "estado": estado,
        "mediana": referencia.get("mediana"),
        "p25": referencia.get("p25"),
        "p75": referencia.get("p75"),
        "vezes_a_mediana": round(vezes, 2),
        "frase": f"{frase} (mediana {referencia.get('mediana')}, {f'{vezes:.1f}'.replace('.', ',')}× essa mediana)",
    }


def analogias(
    sources: Sequence[Dict[str, Any]],
    *,
    contratos: int = CONTRATOS_PADRAO,
    semelhantes: int = SEMELHANTES_PADRAO,
) -> Dict[str, Any]:
    """Para cada contrato das fontes, os contratos semelhantes do mercado.

    `sources` são as fontes que a pesquisa profunda já devolveu (trazem `id` do
    contrato em `idcontrato`/`id`). A referência de mercado de todos os CPV é
    pedida numa única agregação, no fim.
    """
    inicio = time.perf_counter()
    quantos = max(1, min(int(semelhantes or SEMELHANTES_PADRAO), SEMELHANTES_MAX))
    alvos = []
    for item in sources or []:
        if not isinstance(item, dict) or str(item.get("scope") or "") != "contracts":
            continue
        identificador = str(item.get("id") or "").strip()
        if identificador:
            alvos.append(identificador)
        if len(alvos) >= max(1, int(contratos or CONTRATOS_PADRAO)):
            break

    notas: List[str] = []
    if not alvos:
        notas.append("Nenhum contrato com identificador nas fontes: não há analogias para comparar.")
        return {"items": [], "totals": {"contracts": 0, "analogues": 0, "semantic": 0, "by_value": 0}, "notes": notas, "elapsed_ms": 0, "error": None}

    lidos: List[Tuple[str, Dict[str, Any]]] = []
    for identificador in alvos:
        alvo = _ler_alvo(identificador)
        if alvo:
            lidos.append((identificador, alvo))
    if not lidos:
        notas.append("Não foi possível ler os contratos no índice (Elasticsearch sem resposta?).")
        return {"items": [], "totals": {"contracts": len(alvos), "analogues": 0, "semantic": 0, "by_value": 0}, "notes": notas, "error": None}

    # Referência de mercado: uma agregação para todos os CPV das analogias.
    cpvs = [_primeiro_cpv(alvo.get("cpv")) for _, alvo in lidos]
    referencias: Dict[str, Dict[str, Any]] = {}
    try:
        for referencia in deep.mercado_por_cpv([cpv for cpv in cpvs if cpv]):
            referencias[str(referencia.get("cpv"))] = referencia
    except Exception as exc:  # noqa: BLE001 - a posição é um extra
        logger.debug("Analogias: referência de mercado falhou: %s", exc)

    itens: List[Dict[str, Any]] = []
    total_semanticos = 0
    total_por_valor = 0
    total_repetidos = 0
    for identificador, alvo in lidos:
        resumo_alvo = _resumo_do_contrato({**alvo, "idcontrato": identificador})
        semanticos = _vizinhos_semanticos(alvo, quantos)
        encontrados = list(semanticos)
        if semanticos:
            total_semanticos += 1
        if len(encontrados) < quantos:
            # Rede de segurança: completa com o mesmo CPV e valor parecido.
            vistos = {semelhante["id"] for semelhante in encontrados}
            for extra in _vizinhos_por_cpv_e_valor(alvo, quantos - len(encontrados) + len(vistos)):
                if extra["id"] and extra["id"] not in vistos:
                    extra["porque"] = "mesmo CPV e valor na mesma faixa"
                    encontrados.append(extra)
                    vistos.add(extra["id"])
                    if len(encontrados) >= quantos:
                        break
        if not semanticos:
            total_por_valor += 1

        # O índice tem documentos repetidos (o mesmo contrato entrou mais de uma
        # vez, por vezes com outro ano): sem esta limpeza o mesmo semelhante
        # aparecia duas vezes no ecrã. A chave ignora a pontuação e o ano — duas
        # entradas com o mesmo objecto e o mesmo valor não ajudam ninguém.
        vistos_titulo = set()
        unicos: List[Dict[str, Any]] = []
        repetidos = 0
        for semelhante in encontrados:
            chave = (
                re.sub(r"\W+", " ", semelhante["title"].lower()).strip()[:40],
                round(semelhante["preco_valor"], 2),
            )
            if chave in vistos_titulo:
                repetidos += 1
                continue
            vistos_titulo.add(chave)
            unicos.append(semelhante)
        if repetidos:
            total_repetidos += repetidos
        encontrados = unicos[:quantos]

        for semelhante in encontrados:
            semelhante.setdefault("porque", "semelhança semântica com este contrato")
            if semelhante["preco_valor"] and resumo_alvo["preco_valor"]:
                desvio = (semelhante["preco_valor"] - resumo_alvo["preco_valor"]) / resumo_alvo["preco_valor"]
                semelhante["desvio_pct"] = round(desvio * 100, 1)

        cpv_alvo = _primeiro_cpv(alvo.get("cpv"))
        itens.append(
            {
                "contrato": resumo_alvo,
                "semelhantes": encontrados[:quantos],
                "posicao": _posicao_no_mercado(
                    float(alvo.get("precoContratual") or 0.0),
                    referencias.get(str(cpv_alvo or ""), {}),
                ),
            }
        )

    if total_por_valor:
        notas.append(
            f"{total_por_valor} de {len(itens)} contratos não tinham vector: "
            "as analogias vieram do CPV e da faixa de valor."
        )
    if total_repetidos:
        notas.append(
            f"{total_repetidos} semelhante(s) repetido(s) no índice foram excluídos "
            "(o mesmo objecto e valor aparece em mais de um documento)."
        )
    if not referencias:
        notas.append("Sem referência de mercado (não houve CPV suficiente) — os valores aparecem sem posição relativa.")

    return {
        "items": itens,
        "totals": {
            "contracts": len(itens),
            "analogues": sum(len(item["semelhantes"]) for item in itens),
            "semantic": total_semanticos,
            "by_value": total_por_valor,
        },
        "notes": notas,
        "elapsed_ms": int((time.perf_counter() - inicio) * 1000),
        "error": None,
    }
