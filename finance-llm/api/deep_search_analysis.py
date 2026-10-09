"""Ontologia, analogias e análise de um resultado da **pesquisa profunda**.

A pesquisa profunda devolve fontes numeradas. Este módulo pega nessas fontes (as
mesmas que a página já mostrou, para não se repetir a recuperação) e constrói as
três coisas que a página mostra em separadores:

1. **Ontologia** (`ontologia_das_fontes`) — os objectos que aparecem nas fontes
   (contratos, empresas, organismos públicos, CPV, anos) e as relações reais
   entre eles. O valor está nas relações **entre entidades**, que não se vêem
   olhando para um contrato de cada vez: que empresas contrata o mesmo
   organismo, e que empresas aparecem juntas no mesmo comprador. Sai no mesmo
   envelope do `elasticsearch_client.build_contract_graph`, para a interface
   reutilizar o mesmo `GraphCanvas` sem código de grafo novo.
2. **Analogias** (`analogias`) — para cada contrato, os contratos semelhantes do
   mercado (ver `deep_search_analogies.py`, que é quem fala com o kNN).
3. **Análise** (`analisar`) — o texto que interpreta o grafo e as analogias:
   escrito pelo modelo configurado pelo utilizador (`motor="modelo"`) ou pedido
   ao **agente Hermes** (`motor="hermes"`), que junta a sua própria recolha
   federada e devolve evidências citáveis.

Nada aqui inventa dados: sem fontes com contrato, entidade ou CPV não há nós.
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

#: Dimensão da ontologia: uma só, porque os tipos de objecto distinguem-se pelo
#: `type` do nó (ver `ONTOLOGY_TYPES`). O envelope do grafo exige o nome.
ONTOLOGY_DIMENSION = "ontologia"

#: Tipos de nó. As chaves `type` são as que o `TYPE_COLORS`/`TYPE_LABELS` do
#: frontend já conhece (entidade, processo, cpv, tempo, pessoa), para o desenho
#: ser coerente com o resto da plataforma.
ONTOLOGY_TYPES = {
    "entidade": "Empresas e organismos",
    "processo": "Contratos",
    "cpv": "Classificação CPV",
    "tempo": "Anos",
    "pessoa": "Pessoas",
}

#: Papéis das entidades (é o que distingue quem contrata de quem é contratado).
ROLE_ADJUDICANTE = "adjudicante"
ROLE_ADJUDICATARIO = "adjudicatario"

#: Tetos: acima disto o grafo deixa de se ler (e o `GraphCanvas` só desenha 110
#: nós). O que fica de fora é contado nas notas, nunca escondido em silêncio.
ONTOLOGY_MAX_NODES = 90
ONTOLOGY_MAX_EDGES = 200
MERMAID_MAX_NODES = 40
MERMAID_MAX_EDGES = 60

#: Âmbitos que contribuem objectos para a ontologia. Notícias e imprensa ficam de
#: fora: são contexto, não têm chave que as ligue a uma entidade sem inventar.
ONTOLOGY_SCOPES = ("contracts", "contracts_es", "entities", "entities_es", "pessoas", "politicos")

#: Analogias: quantos contratos da resposta se comparam e quantos semelhantes
#: cada um traz.
ANALOGIA_CONTRATOS = 3
ANALOGIA_SEMELHANTES = 3
#: Sem vector, a semelhança é «mesmo CPV e valor dentro desta banda».
ANALOGIA_BANDA_VALOR = 0.5
ANALOGIA_TIMEOUT = 12.0

#: Análise: o Hermes limita a pergunta a 2000 caracteres, por isso o resumo que
#: lhe é enviado é cortado antes disso.
ANALISE_MAX_DIGEST = 1800
ANALISE_MAX_TOKENS = 1100


# --------------------------------------------------------------------- auxiliares

def _texto(valor: Any, limite: int = 90) -> str:
    """Texto de uma linha, sem espaços a mais, cortado com reticências."""
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1].rstrip() + "…"


def _numero(valor: Any) -> float:
    """Valor numérico tolerante (o ES devolve None, "1.234" ou número)."""
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        try:
            return float(valor.replace(" ", "").replace(",", "."))
        except ValueError:
            return 0.0
    return 0.0


def _chave(nif: Any, nome: Any) -> str:
    """Chave estável de uma entidade: o NIF quando existe, senão o nome dobrado.

    Sem NIF não há como juntar a mesma empresa em dois contratos — as notas da
    ontologia dizem quantas entidades ficaram só com nome.
    """
    limpo = str(nif or "").strip()
    if limpo:
        return limpo
    return "nome:" + deep._fold(str(nome or ""))[:60]


def _id_no(tipo: str, chave: str) -> str:
    return f"{tipo}|{chave}"


def _escape_mermaid(texto: str) -> str:
    """Aspas e quebras numa etiqueta Mermaid (as aspas duplas fecham o rótulo)."""
    return texto.replace('"', "#quot;").replace("\n", " ").replace("<", "(").replace(">", ")")


def _id_mermaid(no_id: str) -> str:
    """Identificador Mermaid: só letras, dígitos e `_`."""
    return "n" + re.sub(r"[^A-Za-z0-9]", "_", no_id)[:60]


# --------------------------------------------------------------------- ontologia

class _Ontologia:
    """Acumulador de nós e arestas, com agregação por chave.

    Serve para juntar o que vem de vários contratos: a mesma empresa aparece em
    vários, e o nó tem de ficar com a soma (senão o grafo mostra dez nós iguais).
    """

    def __init__(self) -> None:
        self.nos: Dict[str, Dict[str, Any]] = {}
        self.arestas: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self.sem_nif = 0
        self.fontes_fora = 0

    def no(
        self,
        tipo: str,
        chave: str,
        label: str,
        *,
        role: Optional[str] = None,
        count: int = 1,
        total_value: float = 0.0,
        **extra: Any,
    ) -> str:
        identificador = _id_no(tipo, chave)
        atual = self.nos.get(identificador)
        if atual is None:
            atual = {
                "id": identificador,
                "key": str(chave),
                "label": _texto(label) or str(chave),
                "dimension": ONTOLOGY_DIMENSION,
                "type": tipo,
                "role": role,
                "count": 0,
                "total_value": 0.0,
            }
            self.nos[identificador] = atual
        elif role and not atual.get("role"):
            atual["role"] = role
        if count:
            atual["count"] = int(atual.get("count") or 0) + int(count)
        if total_value:
            atual["total_value"] = _numero(atual.get("total_value")) + float(total_value)
        for campo, valor in extra.items():
            if valor not in (None, "", []):
                atual.setdefault(campo, valor)
        return identificador

    def aresta(self, origem: str, destino: str, label: str, *, count: int = 1, value: float = 0.0) -> None:
        if not origem or not destino or origem == destino:
            return
        chave = (origem, destino, label)
        atual = self.arestas.get(chave)
        if atual is None:
            self.arestas[chave] = {
                "id": f"{origem}->{destino}:{label}",
                "source": origem,
                "target": destino,
                "label": label,
                "kind": label,
                "count": int(count),
                "value": float(value),
            }
            return
        atual["count"] = int(atual["count"]) + int(count)
        atual["value"] = float(atual["value"]) + float(value)

    def arestas_entidades(self, *, pares_por_comprador: int = 12) -> None:
        """Liga as entidades entre si através dos contratos que partilham.

        As arestas contrato→parte dizem quem está em cada contrato; o que se lê
        mal assim é a **rede do mercado**: que empresas contrata o mesmo
        organismo e que empresas aparecem juntas no mesmo comprador. Estas
        arestas somam-se por par (`count` = contratos que os ligam), e é daqui
        que sai boa parte do que a análise depois interpreta.
        """
        por_contrato: Dict[str, Dict[str, Any]] = {}
        for aresta in list(self.arestas.values()):
            if not str(aresta["source"]).startswith("processo|"):
                continue
            rotulo = aresta["label"]
            if rotulo not in ("adjudicado por", "adjudicado a"):
                continue
            registo = por_contrato.setdefault(
                aresta["source"], {"adjudicantes": [], "adjudicatarios": [], "value": 0.0}
            )
            if rotulo == "adjudicado por":
                registo["adjudicantes"].append(aresta["target"])
            else:
                registo["adjudicatarios"].append(aresta["target"])
            registo["value"] = max(_numero(registo["value"]), _numero(aresta["value"]))

        compradores: Dict[str, List[str]] = {}
        for registo in por_contrato.values():
            for adjudicante in registo["adjudicantes"]:
                for adjudicatario in registo["adjudicatarios"]:
                    self.aresta(adjudicante, adjudicatario, "contrata com", count=1, value=registo["value"])
                    lista = compradores.setdefault(str(adjudicante), [])
                    if str(adjudicatario) not in lista:
                        lista.append(str(adjudicatario))

        # Dois fornecedores do mesmo organismo aparecem no mesmo mercado: para
        # poucos fornecedores é informação, para muitos seria ruído (daí o teto).
        for fornecedores in compradores.values():
            if len(fornecedores) > pares_por_comprador:
                continue
            for indice, um in enumerate(fornecedores):
                for outro in fornecedores[indice + 1:]:
                    self.aresta(um, outro, "mesmo comprador")


def _enriquecer_entidades(nifs: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Dados do cadastro (`finance_entities`) para os NIF da ontologia.

    Não é essencial: dá o nome oficial, o CAE e os totais globais. Uma consulta
    só para todos os NIF (é o mesmo índice que a Pesquisa total usa).
    """
    limpos = [nif for nif in dict.fromkeys(str(n or "").strip() for n in nifs) if nif]
    if not limpos:
        return {}
    es = search_service.get_es_client()
    if es is None:
        return {}
    try:
        resposta = es.search(
            index=vectors.ENTITIES_INDEX,
            body={
                "size": len(limpos),
                "query": {"terms": {"nif": limpos}},
                "_source": ["nif", "name", "contracts_count", "total_value", "cae_principal", "country"],
            },
            request_timeout=ANALOGIA_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - enriquecer é um extra
        logger.debug("Ontologia: cadastro de entidades indisponível: %s", exc)
        return {}
    encontrados: Dict[str, Dict[str, Any]] = {}
    for hit in ((resposta.get("hits") or {}).get("hits") or []):
        origem = hit.get("_source") or {}
        nif = str(origem.get("nif") or "").strip()
        if nif:
            encontrados[nif] = origem
    return encontrados


def _partes_do_contrato(item: Dict[str, Any]) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """`[(role, nome, nif)]` das partes de uma fonte de contrato.

    As fontes da pesquisa profunda já trazem isto em `meta` (foi acrescentado
    para as fichas poderem abrir); usa-se também `links` como alternativa, para
    ontologias construídas a partir de fontes mais antigas.
    """
    meta = item.get("meta") or {}
    partes: List[Tuple[str, Optional[str], Optional[str]]] = []
    for role, chave_nome, chave_nif in (
        (ROLE_ADJUDICANTE, "adjudicante", "adjudicante_nif"),
        (ROLE_ADJUDICATARIO, "adjudicatario", "adjudicatario_nif"),
    ):
        nome = meta.get(chave_nome)
        if isinstance(nome, str) and nome.strip():
            nif = meta.get(chave_nif)
            partes.append((role, nome.strip(), str(nif).strip() if nif else None))
    if partes:
        return partes

    # Alternativa: as ligações já calculadas («Entidade adjudicante», «Adjudicatário»).
    for ligacao in item.get("links") or []:
        if not isinstance(ligacao, dict):
            continue
        rotulo = str(ligacao.get("label") or "").lower()
        if "adjudicante" in rotulo:
            partes.append((ROLE_ADJUDICANTE, str(ligacao.get("text") or "").strip(), str(ligacao.get("arg") or "").strip() or None))
        elif "adjudicat" in rotulo:
            partes.append((ROLE_ADJUDICATARIO, str(ligacao.get("text") or "").strip(), str(ligacao.get("arg") or "").strip() or None))
    return [parte for parte in partes if parte[1]]


def ontologia_das_fontes(sources: Sequence[Dict[str, Any]], *, enriquecer: bool = True) -> Dict[str, Any]:
    """Grafo de objectos e relações construído a partir das fontes da resposta.

    Devolve o mesmo envelope do `build_contract_graph` (nós com `count` e
    `total_value`, arestas com `count` e `value`, e um `meta`) mais três extras
    que a página usa: `legend`, `totals` e `mermaid`.
    """
    inicio = time.perf_counter()
    grafo = _Ontologia()
    usados = 0
    sem_cpv = 0
    contratos = 0

    for item in sources or []:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope") or "")
        if scope not in ONTOLOGY_SCOPES:
            grafo.fontes_fora += 1
            continue
        usados += 1
        meta = item.get("meta") or {}
        identificador = str(item.get("id") or "").strip()

        # --- contratos (Portugal e Espanha): o objecto central da ontologia ---
        if scope in ("contracts", "contracts_es"):
            chave_contrato = identificador or str(item.get("title") or "")
            if not chave_contrato:
                continue
            valor = _numero(meta.get("preco") or meta.get("valor"))
            contrato = grafo.no(
                "processo",
                chave_contrato,
                item.get("title") or "Contrato",
                count=1,
                total_value=valor,
                scope=scope,
                subtitulo=_texto(item.get("subtitle"), 70),
                valor=_numero(meta.get("preco")),
            )
            contratos += 1

            for role, nome, nif in _partes_do_contrato(item):
                if not nif:
                    grafo.sem_nif += 1
                # O valor entra no nó da entidade: é o que permite ver, no grafo,
                # quem concentra dinheiro e não apenas quem tem mais contratos.
                entidade = grafo.no("entidade", _chave(nif, nome), nome, role=role, count=1, total_value=valor)
                etiqueta = "adjudicado por" if role == ROLE_ADJUDICANTE else "adjudicado a"
                grafo.aresta(contrato, entidade, etiqueta, count=1, value=valor)

            codigo_cpv = str(meta.get("cpv") or "").strip()
            if codigo_cpv:
                no_cpv = grafo.no("cpv", codigo_cpv, codigo_cpv, count=1, total_value=valor)
                grafo.aresta(contrato, no_cpv, "classificado como", count=1, value=valor)
            else:
                sem_cpv += 1

            ano = str(meta.get("ano") or (item.get("date") or "")[:4] or "").strip()
            if ano.isdigit():
                no_ano = grafo.no("tempo", ano, ano, count=1, total_value=valor)
                grafo.aresta(contrato, no_ano, "celebrado em", count=1, value=valor)
            continue

        # --- entidades já identificadas (cadastro) e pessoas ---
        if scope in ("entities", "entities_es"):
            nome = str(item.get("title") or meta.get("adjudicante") or "").strip()
            nif = meta.get("nif") or (item.get("open") or {}).get("arg")
            if nome or nif:
                grafo.no(
                    "entidade",
                    _chave(nif, nome),
                    nome or str(nif),
                    count=int(_numero(meta.get("contratos")) or 0),
                    total_value=_numero(meta.get("valor")),
                    scope=scope,
                )
            continue

        if scope in ("pessoas", "politicos"):
            nome = str(item.get("title") or "").strip()
            if nome:
                grafo.no(
                    "pessoa",
                    _chave(item.get("id"), nome),
                    nome,
                    count=int(_numero(meta.get("contratos")) or 0),
                    total_value=_numero(meta.get("valor")),
                    scope=scope,
                )

    # --- relações entre entidades, que é onde está o valor da ontologia ---
    grafo.arestas_entidades()

    # --- cadastro: nome oficial, CAE e dimensão real da entidade ---
    if enriquecer:
        nifs = [
            no["key"]
            for no in grafo.nos.values()
            if no["type"] == "entidade" and str(no["key"]).isdigit()
        ]
        cadastro = _enriquecer_entidades(nifs)
        for no in grafo.nos.values():
            if no["type"] != "entidade":
                continue
            dados = cadastro.get(str(no["key"]))
            if not dados:
                continue
            no["label"] = _texto(dados.get("name") or no["label"])
            no["cae"] = dados.get("cae_principal")
            no["global_contracts"] = int(_numero(dados.get("contracts_count")))
            no["global_value"] = _numero(dados.get("total_value"))
            no["country"] = dados.get("country")

    return _empacotar(grafo, usados=usados, contratos=contratos, sem_cpv=sem_cpv, inicio=inicio)


def _empacotar(
    grafo: _Ontologia,
    *,
    usados: int,
    contratos: int,
    sem_cpv: int,
    inicio: float,
) -> Dict[str, Any]:
    """Corta, ordena e embrulha nós/arestas no envelope do grafo de contratos."""
    nos = sorted(grafo.nos.values(), key=lambda no: (-int(no.get("count") or 0), -_numero(no.get("total_value"))))
    arestas = sorted(
        grafo.arestas.values(),
        key=lambda aresta: (-int(aresta.get("count") or 0), -_numero(aresta.get("value"))),
    )
    nos_cortados = max(0, len(nos) - ONTOLOGY_MAX_NODES)
    arestas_cortadas = max(0, len(arestas) - ONTOLOGY_MAX_EDGES)
    nos = nos[:ONTOLOGY_MAX_NODES]
    mantidos = {no["id"] for no in nos}
    arestas = [a for a in arestas if a["source"] in mantidos and a["target"] in mantidos][:ONTOLOGY_MAX_EDGES]

    notas: List[str] = []
    if nos_cortados:
        notas.append(f"{nos_cortados} objecto(s) ficaram de fora: só se desenham {ONTOLOGY_MAX_NODES}.")
    if arestas_cortadas:
        notas.append(f"{arestas_cortadas} relação(ões) ficaram de fora do grafo.")
    if grafo.sem_nif:
        notas.append(
            f"{grafo.sem_nif} parte(s) sem NIF: contam como entidade à parte, "
            "por isso a mesma empresa pode aparecer em dois nós."
        )
    if sem_cpv:
        notas.append(f"{sem_cpv} contrato(s) sem código CPV.")
    if grafo.fontes_fora:
        notas.append(f"{grafo.fontes_fora} fonte(s) fora da ontologia (notícias e imprensa são contexto, não objectos).")
    if contratos == 0:
        notas.append("Nenhuma fonte desta resposta é um contrato: a ontologia mostra só as entidades encontradas.")

    por_tipo: Dict[str, int] = {}
    for no in nos:
        por_tipo[no["type"]] = por_tipo.get(no["type"], 0) + 1

    return {
        "nodes": nos,
        "edges": arestas,
        "meta": {
            "dimension_a": ONTOLOGY_DIMENSION,
            "dimension_b": None,
            "metric": "contratos",
            "mode": "ontologia",
            "complete": not (nos_cortados or arestas_cortadas),
            "sample_order": "count",
            "documents_scanned": usados,
            "documents_matching": contratos,
            "scanned_value": sum(_numero(no.get("total_value")) for no in nos),
            "nodes_total": len(grafo.nos),
            "edges_total": len(grafo.arestas),
            "kept_nodes": len(nos),
            "kept_edges": len(arestas),
            "omitted_edges": arestas_cortadas,
            "directed": True,
            "limits": {"max_nodes": ONTOLOGY_MAX_NODES, "max_edges": ONTOLOGY_MAX_EDGES},
            "notes": notas,
            "filters": {"scopes": list(ONTOLOGY_SCOPES)},
        },
        "legend": [
            {"type": tipo, "label": rotulo, "count": por_tipo.get(tipo, 0)}
            for tipo, rotulo in ONTOLOGY_TYPES.items()
            if por_tipo.get(tipo)
        ],
        "totals": {
            "nodes": len(nos),
            "edges": len(arestas),
            "by_type": por_tipo,
            "scopes": usados,
            "contracts": contratos,
        },
        "mermaid": mermaid_da_ontologia(nos, arestas),
        "elapsed_ms": int((time.perf_counter() - inicio) * 1000),
        "error": None,
    }


def mermaid_da_ontologia(nodes: Sequence[Dict[str, Any]], edges: Sequence[Dict[str, Any]]) -> str:
    """Diagrama Mermaid do grafo.

    `a -->|"adjudicado a"| b` é a forma que o Mermaid aceita; sem aspas um rótulo
    com parênteses ou vírgulas rebenta o diagrama.
    """
    nos = list(nodes)[:MERMAID_MAX_NODES]
    mantidos = {no["id"] for no in nos}
    utilizadas = [a for a in edges if a["source"] in mantidos and a["target"] in mantidos][:MERMAID_MAX_EDGES]
    if not nos:
        return ""

    linhas = ["graph LR"]
    for no in nos:
        etiqueta = _escape_mermaid(_texto(no.get("label"), 42))
        if no.get("role"):
            etiqueta += f" ({no['role']})"
        linhas.append(f'  {_id_mermaid(no["id"])}["{etiqueta}"]')
    for aresta in utilizadas:
        rotulo = _escape_mermaid(_texto(aresta.get("label"), 24))
        linhas.append(
            f'  {_id_mermaid(aresta["source"])} -->|"{rotulo}"| {_id_mermaid(aresta["target"])}'
        )
    return "\n".join(linhas)


# --------------------------------------------------------------------- análise

#: Instrução do analista. É curta de propósito: quem escreve é o modelo que o
#: utilizador escolheu, e o que ele vê é o resumo abaixo.
PROMPT_SISTEMA_ANALISE = (
    "És analista de contratação pública do IQ OS. Recebes a **ontologia** de uma "
    "resposta (objectos e relações reais, tirados dos contratos) e as **analogias** "
    "desses contratos no mercado. Interpretas o que está lá: quem domina, que "
    "relações se repetem, o que foge ao padrão e o que os valores mostram face à "
    "mediana do mesmo CPV. Não inventas entidades, valores nem relações que não "
    "estejam no resumo; quando algo não se puder concluir, di-lo."
)

TAREFA_ANALISE = (
    "\n\n### Tarefa\n"
    "Interpreta a ontologia e as analogias acima, em português de Portugal e em "
    "texto corrido curto (usa bullets ou tabela só se ajudar). Diz: (1) que "
    "objectos e relações dominam; (2) o que as analogias mostram sobre os valores; "
    "(3) que padrões ou anomalias se vêem; (4) o que não se pode concluir com "
    "estes dados. Termina com uma secção «**Notas**»."
)


def _rotulos(ontologia: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """`{id do nó: rótulo}` para o resumo poder nomear as pontas de cada aresta."""
    return {
        str(no.get("id")): str(no.get("label") or no.get("key") or "")
        for no in (ontologia or {}).get("nodes") or []
        if isinstance(no, dict)
    }


def _digest(
    pergunta: str,
    ontologia: Optional[Dict[str, Any]],
    analogias: Optional[Dict[str, Any]],
    sources: Sequence[Dict[str, Any]],
    *,
    limite: int = ANALISE_MAX_DIGEST,
) -> str:
    """Resumo textual do grafo e das analogias, para o modelo ou para o Hermes.

    O Hermes limita a pergunta a 2000 caracteres e o `ask()` não aceita contexto
    estruturado (só texto), por isso a ontologia vai **dentro** da pergunta, em
    texto compacto.
    """
    linhas: List[str] = [f"### Pergunta\n{_texto(pergunta, 240)}"]
    rotulos = _rotulos(ontologia)

    nos = [no for no in (ontologia or {}).get("nodes") or [] if isinstance(no, dict)]
    arestas = [a for a in (ontologia or {}).get("edges") or [] if isinstance(a, dict)]
    if nos:
        por_tipo: Dict[str, List[Dict[str, Any]]] = {}
        for no in nos:
            por_tipo.setdefault(str(no.get("type") or "outra"), []).append(no)
        contagem = ", ".join(f"{len(lista)} {tipo}" for tipo, lista in por_tipo.items())
        linhas.append(f"\n### Ontologia ({len(nos)} objectos, {len(arestas)} relações: {contagem})")

        entidades = sorted(por_tipo.get("entidade", []), key=lambda no: -int(no.get("count") or 0))
        if entidades:
            linhas.append(
                "- Objectos com mais contratos na resposta: "
                + "; ".join(
                    f"{_texto(no.get('label'), 38)} ({int(no.get('count') or 0)}"
                    + (f", {no['cae']}" if no.get("cae") else "")
                    + ")"
                    for no in entidades[:8]
                )
            )
        contratos = por_tipo.get("processo", [])
        if contratos:
            soma = sum(_numero(no.get("total_value")) for no in contratos)
            linhas.append(f"- Contratos: {len(contratos)} · valor somado {deep._euros(soma) or '—'}")
        cpvs = por_tipo.get("cpv", [])
        if cpvs:
            linhas.append(
                "- CPV: "
                + "; ".join(f"{no.get('label')} ({int(no.get('count') or 0)})" for no in cpvs[:6])
            )

        fortes = sorted(arestas, key=lambda a: (-int(a.get("count") or 0), -_numero(a.get("value"))))
        if fortes:
            linhas.append("- Relações mais fortes:")
            for aresta in fortes[:10]:
                origem = _texto(rotulos.get(str(aresta.get("source")), str(aresta.get("source"))), 32)
                destino = _texto(rotulos.get(str(aresta.get("target")), str(aresta.get("target"))), 32)
                linhas.append(f"  · {origem} --{aresta.get('label')}--> {destino} ({int(aresta.get('count') or 0)})")

    itens = [item for item in (analogias or {}).get("items") or [] if isinstance(item, dict)]
    if itens:
        linhas.append("\n### Analogias (contratos semelhantes no mercado)")
        for item in itens[:CONTRATOS_NO_DIGEST]:
            contrato = item.get("contrato") or {}
            posicao = item.get("posicao") or {}
            linhas.append(
                f"- «{_texto(contrato.get('title'), 46)}» — {contrato.get('preco') or '—'}"
                f" · CPV {contrato.get('cpv') or '—'} · {posicao.get('frase') or 'sem referência de mercado'}"
            )
            for semelhante in (item.get("semelhantes") or [])[:3]:
                desvio = semelhante.get("desvio_pct")
                linhas.append(
                    f"  · {_texto(semelhante.get('title'), 44)} — {semelhante.get('preco') or '—'}"
                    + (f" ({desvio:+.1f}% vs este)".replace(".", ",") if isinstance(desvio, (int, float)) else "")
                    + f" · {semelhante.get('porque') or ''}"
                )

    fontes = [fonte for fonte in sources or [] if isinstance(fonte, dict)]
    if fontes:
        linhas.append("\n### Fontes (numeração igual à da resposta)")
        for fonte in fontes[:10]:
            detalhe = deep._meta_linha(fonte.get("meta") or {})
            linhas.append(
                f"[{fonte.get('n')}] {_texto(fonte.get('title'), 54)}"
                + (f" — {_texto(detalhe, 70)}" if detalhe else "")
            )

    return "\n".join(linhas)[:limite]


#: Contratos das analogias que entram no resumo (o resto só ocuparia espaço).
CONTRATOS_NO_DIGEST = 3


async def analisar(
    pergunta: str,
    *,
    ontologia: Optional[Dict[str, Any]] = None,
    analogias: Optional[Dict[str, Any]] = None,
    sources: Optional[Sequence[Dict[str, Any]]] = None,
    motor: str = "modelo",
    backend: str = "",
    user_id: Optional[str] = None,
    session: Any = None,
    depth: str = "profunda",
) -> Dict[str, Any]:
    """Interpreta a ontologia e as analogias: pelo modelo escolhido ou pelo Hermes.

    Devolve sempre a mesma forma, com `motor` a dizer quem escreveu, para a página
    poder mostrar o mesmo painel nos dois casos. Nunca levanta: um erro do
    fornecedor sai em `error`, como no resto da pesquisa profunda.
    """
    inicio = time.perf_counter()
    resumo = _digest(pergunta, ontologia, analogias, sources or [])
    if not (ontologia or {}).get("nodes") and not (analogias or {}).get("items"):
        return {
            "motor": motor or "modelo",
            "modelo": None,
            "texto": "",
            "evidencias": [],
            "passos": [],
            "notes": [],
            "elapsed_ms": int((time.perf_counter() - inicio) * 1000),
            "error": "Não há ontologia nem analogias para analisar.",
        }

    if str(motor or "modelo").lower() == "hermes":
        return await _analisar_com_hermes(pergunta, resumo, session=session, depth=depth, inicio=inicio)
    return await _analisar_com_modelo(pergunta, resumo, backend=backend, user_id=user_id, inicio=inicio)


async def _analisar_com_modelo(
    pergunta: str,
    resumo: str,
    *,
    backend: str,
    user_id: Optional[str],
    inicio: float,
) -> Dict[str, Any]:
    """Análise pelo modelo configurado (o mesmo caminho de resposta da plataforma)."""
    decidido = deep.resolve_backend(backend, user_id)
    messages = [
        {"role": "system", "content": PROMPT_SISTEMA_ANALISE},
        {"role": "user", "content": resumo + TAREFA_ANALISE},
    ]
    partes: List[str] = []
    erro: Optional[str] = None
    try:
        async for pedaco in deep._stream_model(
            messages,
            backend=decidido,
            user_id=user_id,
            temperature=0.2,
            max_tokens=ANALISE_MAX_TOKENS,
        ):
            partes.append(pedaco)
    except Exception as exc:  # noqa: BLE001 - a página mostra a razão
        logger.warning("Análise da ontologia: o modelo %s falhou: %s", decidido.get("label"), exc)
        erro = str(exc)
    texto = "".join(partes).strip()
    return {
        "motor": "modelo",
        "modelo": decidido.get("label"),
        "texto": texto,
        "evidencias": [],
        "passos": [],
        "notes": [],
        "elapsed_ms": int((time.perf_counter() - inicio) * 1000),
        "error": None if texto else (erro or "O modelo não devolveu texto."),
    }


async def _analisar_com_hermes(
    pergunta: str,
    resumo: str,
    *,
    session: Any,
    depth: str,
    inicio: float,
) -> Dict[str, Any]:
    """Análise pelo **agente Hermes**, que acrescenta a sua própria recolha.

    `hermes_service.ask` só recebe texto (não aceita contexto estruturado) e
    limita a pergunta a 2000 caracteres: é por isso que o resumo vai colado à
    pergunta, já cortado.
    """
    try:
        from api import hermes_service
    except Exception as exc:  # noqa: BLE001
        return {
            "motor": "hermes",
            "modelo": None,
            "texto": "",
            "evidencias": [],
            "passos": [],
            "notes": [],
            "elapsed_ms": int((time.perf_counter() - inicio) * 1000),
            "error": f"Módulo do Hermes indisponível: {exc}",
        }

    questao = (resumo + TAREFA_ANALISE)[:1950]
    try:
        resposta = await hermes_service.ask(questao, depth=depth, session=session, country="PRT")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Análise da ontologia: o Hermes falhou: %s", exc)
        return {
            "motor": "hermes",
            "modelo": None,
            "texto": "",
            "evidencias": [],
            "passos": [],
            "notes": [],
            "elapsed_ms": int((time.perf_counter() - inicio) * 1000),
            "error": f"O agente Hermes falhou: {exc}",
        }

    passos = [
        {
            "focus": passo.get("focus"),
            "question": passo.get("question"),
            "items": passo.get("items"),
            "sources_with_results": passo.get("sources_with_results"),
            "ms": passo.get("ms"),
        }
        for passo in (resposta.get("steps") or [])
        if isinstance(passo, dict)
    ]
    return {
        "motor": "hermes",
        "modelo": (resposta.get("backend") or {}).get("label"),
        "modo": resposta.get("mode"),
        "texto": str(resposta.get("text") or "").strip(),
        "evidencias": resposta.get("evidence") or [],
        "passos": passos,
        "facts": resposta.get("facts") or [],
        "notes": list(resposta.get("notes") or []) + list(resposta.get("warnings") or []),
        "followups": resposta.get("followups") or [],
        "stats": resposta.get("stats"),
        "elapsed_ms": int((time.perf_counter() - inicio) * 1000),
        "error": None,
    }
