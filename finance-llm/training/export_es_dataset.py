"""Exporta datasets de treino (formato Alpaca) a partir do Elasticsearch.

O IQ OS guarda nos índices do Elasticsearch os dados com que responde. Este
script transforma esses documentos em pares ``instruction``/``input``/
``output`` — o mesmo formato de ``data/final/contratos_train.jsonl`` e o que o
``soup`` deteta sozinho (``data.format: alpaca`` nos configs de
``training/soup/``).

Exemplos:
    python training/export_es_dataset.py --list
    python training/export_es_dataset.py --dataset contratos --max-records 20000
    python training/export_es_dataset.py --dataset noticias --out data/final/sentimento.jsonl
    python training/export_es_dataset.py --dataset empresas --query '{"term": {"country_code": "PT"}}'

O ``--dataset`` pode repetir-se para juntar várias fontes **no mesmo** ficheiro —
é assim que se treina um só modelo sobre contratos e empresas:::

    python training/export_es_dataset.py --dataset contratos --dataset empresas \
        --max-records 400 --seed 42 --out data/final/iqos_contratos_empresas.jsonl

Com várias fontes, o ``--max-records`` conta por fonte (400 de contratos **e** 400
de empresas) e cada linha fica com ``metadata.fonte`` a dizer de onde veio.

Índice à medida (sem receita): dá-se a instrução e os moldes de entrada/saída,
com ``{campo}`` substituídos por campos de topo do documento::

    python training/export_es_dataset.py --index finance_news \
        --instruction "Resume esta notícia." \
        --input-template "{title}" --output-template "{summary_pt}" \
        --fields title,summary_pt

O treino recusa (não corta) linhas que não cabem na janela do modelo — o
``soup train`` aborta se alguma ficar sem resposta depois da truncagem. Com
``--tokenizer`` e ``--max-tokens`` o exporter mede cada par com o tokenizer do
modelo e deixa de fora os que não caibam::

    python training/export_es_dataset.py --dataset contratos --max-records 200000 \
        --tokenizer model/mistral-finance/final --max-tokens 950

Um índice não está baralhado: os primeiros N documentos costumam vir todos do
mesmo ficheiro de origem (o mesmo organismo, o mesmo ano). Para treinar com uma
amostra representativa use ``--seed``, que pede ao Elasticsearch uma amostra
dispersa::

    python training/export_es_dataset.py --dataset subvencoes --max-records 800 --seed 42

O ficheiro é escrito em UTF-8, uma linha por exemplo, e só substitui o destino
no fim — nunca fica um dataset truncado a meio.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import (  # noqa: E402
    CONTRACTS_INDEX,
    CONTRATOS_ES_INDEX,
    CONTRATOS_FR_INDEX,
    ENTITIES_INDEX,
    SUBVENCOES_INDEX,
    get_es_client,
)

# `finance_news` não tem constante no cliente (lá aparece como literal).
NEWS_INDEX = "finance_news"

DEFAULT_OUT_DIR = ROOT / "data" / "final"
DEFAULT_MAX_RECORDS = 50_000
DEFAULT_MAX_CHARS = 4_000

# Campo em falta, na língua da receita (as respostas são escritas na língua do
# país do contrato, com o texto de ligação em português).
_EMPTY: Dict[str, str] = {"pt": "não especificado", "es": "no especificado", "fr": "non précisé"}

logger = logging.getLogger("export_es_dataset")


# ---------------------------------------------------------------------------
# Normalização dos campos do Elasticsearch
# ---------------------------------------------------------------------------
def _clean(value: Any) -> str:
    """Colapsa espaços (os documentos trazem quebras de linha e tabulações).

    Desfaz também entidades HTML: os nomes no Elasticsearch vêm com ``&amp;``,
    e sem isto o modelo aprendia a escrever ``OLIVEIRA &amp; PIRES``.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip() + "…"
    return text


def _names(field_value: Any) -> List[str]:
    """Nomes de ``adjudicantes``/``adjudicatarios``/``titulaires``.

    Os documentos guardam ``{"raw": [...], "parsed": [{"nif": ..., "nome": ...}]}``;
    ``parsed`` traz o nome limpo, ``raw`` (com o NIF à frente) é a alternativa.
    Listas de nomes simples e listas de objectos (``nom``/``nome``/``name``, como
    os ``titulaires`` franceses) também são aceites.
    """
    if isinstance(field_value, dict):
        nomes = [
            _clean(item.get("nome") or item.get("nom") or item.get("name"))
            for item in field_value.get("parsed") or []
            if isinstance(item, dict)
        ]
        nomes = [nome for nome in nomes if nome]
        if nomes:
            return nomes
        return [_clean(item) for item in field_value.get("raw") or [] if _clean(item)]
    if isinstance(field_value, (list, tuple)):
        nomes = []
        for item in field_value:
            if isinstance(item, dict):
                nome = _clean(item.get("nome") or item.get("nom") or item.get("name"))
                if not nome:
                    # Sem nome: usa o identificador rotulado («SIRET 34348850800924»),
                    # senão o par ficava sem entidade nenhuma.
                    identificador = _clean(item.get("id"))
                    tipo = _clean(item.get("type_identifiant"))
                    nome = f"{tipo} {identificador}".strip() if identificador else ""
            else:
                nome = _clean(item)
            if nome:
                nomes.append(nome)
        return nomes
    text = _clean(field_value)
    return [text] if text else []


def _cpv_label(cpv: Any, language: str = "pt") -> str:
    """Descrição do CPV principal (``cpv`` é ``[{"code", "description"}]``)."""
    empty = _EMPTY.get(language, _EMPTY["pt"])
    if not isinstance(cpv, (list, tuple)) or not cpv:
        return empty
    first = cpv[0]
    if isinstance(first, dict):
        return _clean(first.get("description") or first.get("descripcion") or first.get("nom") or first.get("code")) or empty
    return _clean(first) or empty


def _money(value: Any, language: str = "pt") -> str:
    if value is None or value == "":
        return _EMPTY.get(language, _EMPTY["pt"])
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return _clean(value)
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} €"


def _num(value: Any, fallback: str = "não especificado") -> str:
    """Contagens: ``None`` vira texto legível em vez de «None» no prompt."""
    if value is None or value == "":
        return fallback
    return _clean(value)


def _listed(value: Any, sep: str = ", ", fallback: str = "não especificado") -> str:
    if isinstance(value, (dict, list, tuple)):
        return sep.join(_names(value)) or fallback
    text = _clean(value)
    return text or fallback


# ---------------------------------------------------------------------------
# Receitas: índice → pares instrução/resposta
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Recipe:
    index: str
    instruction: str
    includes: Tuple[str, ...]
    #: Devolve um par (`prompt`, `completion`, `metadata`) ou, para documentos que
    #: servem várias instruções, uma lista de `(instruction, prompt, completion,
    #: metadata)`. Ver `_build_contrato_pt_variantes`.
    build: Callable[
        [Dict[str, Any], int],
        Union[
            Optional[Tuple[str, str, Dict[str, Any]]],
            Optional[List[Tuple[str, Dict[str, Any], str, Dict[str, Any]]]],
        ],
    ]
    query: Dict[str, Any] = field(default_factory=lambda: {"match_all": {}})


#: Teto do objecto e da descrição que entram no par. A resposta tem 2-3 frases:
#: colar 4 000 caracteres de descrição custa ~27× mais tempo de treino (a atenção
#: é quadrática: 5× mais tokens ≈ 27× mais contas) sem ensinar nada que a
#: resposta use. Medido nesta CPU: 271 tokens/par = 148 s por par; 120 tokens/par
#: = ~30 s.
TEXTO_CAMPO_MAX = 90


def _build_contrato_pt(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Espelha ``collectors/contratos.py::build_training_corpus`` (mesma redação).

    Todos os campos citados na resposta têm de estar no pedido. Faltavam aqui a
    data de publicação, o regime e o CPV — que a resposta já usava — e o modelo
    aprendeu a **inventá-los**: em 245 de 245 exemplos o *output* citava uma data
    e um regime que o *input* não tinha, e o modelo reproduzia essa invenção com
    outra data qualquer (verificado: «publicado a 2021-08-26» para um contrato
    sem data). Com os campos no pedido, a resposta fica ancorada no documento.
    """
    idcontrato = _clean(doc.get("idcontrato"))
    objecto = _truncate(_clean(doc.get("objectoContrato") or doc.get("descContrato")), TEXTO_CAMPO_MAX)
    if not idcontrato or not objecto:
        return None
    adjudicante = _listed(doc.get("adjudicantes"), fallback="não identificado")
    adjudicatario = _listed(doc.get("adjudicatarios"), fallback="não identificado")
    tipo = _listed(doc.get("tipoContrato"))
    procedimento = _clean(doc.get("tipoprocedimento")) or "não especificado"
    preco_raw = doc.get("precoContratual")
    preco = _money(preco_raw)
    descricao = _truncate(_clean(doc.get("descContrato")), TEXTO_CAMPO_MAX)
    data = _clean(doc.get("dataPublicacao")) or "data desconhecida"
    regime = _clean(doc.get("regime")) or "não especificado"
    cpv = _cpv_label(doc.get("cpv"))

    prompt = (
        f"Contrato {idcontrato} - {objecto}\n"
        f"Adjudicante: {adjudicante}\n"
        f"Adjudicatário: {adjudicatario}\n"
        f"Tipo: {tipo}\n"
        f"Procedimento: {procedimento}\n"
        f"Preço contratual: {preco_raw}\n"
        f"Data de publicação: {data}\n"
        f"Regime: {regime}\n"
        f"CPV principal: {cpv}"
        # A descrição só entra quando diz algo para além do objecto: repetir a
        # mesma frase custa tokens (e atenção) sem dar informação nova.
        # Um campo por linha (e não «A | B») porque com separadores o modelo
        # copiava pedaços do pedido para dentro da frase («num procedimento
        # «Concurso publico | Tipo: Aquisicao de bens moveis»»).
        + (f"\nDescrição: {descricao}" if descricao and descricao not in objecto else "")
    )
    completion = (
        f"Este contrato, publicado a {data} e com regime {regime}, liga {adjudicante} "
        f"a {adjudicatario} por {preco}, para {objecto}. CPV: {cpv}."
    )
    return (
        _truncate(prompt, max_chars) if max_chars else prompt,
        completion,
        {"idcontrato": idcontrato, "ano": doc.get("Ano"), "tipoContrato": doc.get("tipoContrato")},
    )


#: Valor a partir do qual um ajuste direto deixa de caber no limite legal
#: (art. 22.º do CCP para bens e serviços). Só serve para sinalizar, não decide.
LIMITE_AJUSTE_DIRETO = 75_000.0


def _valor_numerico(bruto: Any) -> Optional[float]:
    try:
        return float(str(bruto).replace(" ", "").replace(",", ".").replace("€", ""))
    except (TypeError, ValueError):
        return None


def _sinais_de_risco(procedimento: str, preco_raw: Any, adjudicatarios: str) -> str:
    """Sinais objetivos a partir do que está no documento — sem inferir mais nada.

    Serve a instrução «auditar»: a resposta só pode apontar o que o pedido
    permite verificar. Um modelo de 0,5 B não faz auditoria; pode, isso sim,
    destacar os factos que um auditor olharia primeiro.
    """
    sinais: List[str] = []
    texto = procedimento.lower()
    valor = _valor_numerico(preco_raw)
    if "ajuste" in texto and valor is not None and valor > LIMITE_AJUSTE_DIRETO:
        sinais.append(
            f"ajuste direto de {valor:,.2f} € acima do limite legal de "
            f"{LIMITE_AJUSTE_DIRETO:,.2f} €"
        )
    elif "ajuste" in texto:
        sinais.append("ajuste direto: confirmar fundamento e convites")
    elif "concurso" in texto:
        sinais.append("procedimento concorrencial")
    if "não identificado" not in adjudicatarios and "," not in adjudicatarios:
        sinais.append("adjudicatário único")
    return "; ".join(sinais)


def _build_contrato_pt_variantes(
    doc: Dict[str, Any], max_chars: int
) -> Optional[List[Tuple[str, Dict[str, Any], str, Dict[str, Any]]]]:
    """O mesmo contrato com as três instruções que a interface oferece.

    O modelo só tinha visto «Descreve este contrato público português.»; quando
    a página pedia «auditar» ou «responder a cidadão», respondia com a descrição
    decorada (e repetia-se: «o CPV principal principal»). Três instruções sobre o
    mesmo documento ensinam que a instrução muda a resposta — mantendo tudo
    ancorado no pedido.

    Devolve pares ``(instruction, prompt, completion, metadata)``; ver
    :func:`export_many`, que aceita este formato além do par único.
    """
    base = _build_contrato_pt(doc, max_chars)
    if base is None:
        return None
    prompt, completion, metadata = base

    idcontrato = _clean(doc.get("idcontrato"))
    objecto = _truncate(_clean(doc.get("objectoContrato") or doc.get("descContrato")), TEXTO_CAMPO_MAX)
    adjudicante = _listed(doc.get("adjudicantes"), fallback="não identificado")
    adjudicatario = _listed(doc.get("adjudicatarios"), fallback="não identificado")
    procedimento = _clean(doc.get("tipoprocedimento")) or "não especificado"
    preco = _money(doc.get("precoContratual"))
    data = _clean(doc.get("dataPublicacao")) or "data desconhecida"
    cpv = _cpv_label(doc.get("cpv"))

    cidadao = (
        f"{adjudicante} contratou «{objecto}» a {adjudicatario} por {preco}. "
        f"O procedimento foi {procedimento} e o contrato foi publicado a {data}."
    )
    sinais = _sinais_de_risco(procedimento, doc.get("precoContratual"), adjudicatario)
    auditoria = (
        f"A verificar neste contrato: procedimento {procedimento}, valor {preco}, "
        f"adjudicatário {adjudicatario}. "
        + (f"Sinal de risco: {sinais}. " if sinais else "")
        + "O documento não tem dados sobre prazo, garantias ou subcontratação. "
        f"Confirma o enquadramento do procedimento e o CPV {cpv}?"
    )
    return [
        ("Descreve este contrato público português.", prompt, completion, metadata),
        ("Resume este contrato numa frase, para um cidadão.", prompt, cidadao, metadata),
        ("Audita este contrato e aponta o que deve ser verificado.", prompt, auditoria, metadata),
    ]


def _build_contrato_es(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    expediente = _clean(doc.get("id_expediente"))
    objeto = _truncate(_clean(doc.get("objeto") or doc.get("descripcion")), max_chars)
    if not expediente or not objeto:
        return None
    organo = _clean(doc.get("organo_nombre")) or "não identificado"
    adjudicatario = _clean(doc.get("adjudicatario_nombre"))
    if not adjudicatario:
        adjudicatario_nif = _clean(doc.get("adjudicatario_nif"))
        adjudicatario = f"entidade {adjudicatario_nif}" if adjudicatario_nif else "não identificado"
    tipo = _clean(doc.get("tipo_contrato_label") or doc.get("tipo_contrato")) or "não especificado"
    procedimiento = _clean(doc.get("procedimiento_label") or doc.get("procedimiento")) or "não especificado"
    importe = _money(doc.get("valor_adjudicado"))
    fecha = _clean(doc.get("fecha_publicacion")) or "data desconhecida"
    localidad = _clean(doc.get("localidad")) or "não especificada"

    prompt = (
        f"Expediente {expediente} - {objeto}\n"
        f"Órgão: {organo}\n"
        f"Adjudicatário: {adjudicatario}\n"
        f"Tipo: {tipo}\n"
        f"Procedimento: {procedimiento}\n"
        f"Valor adjudicado: {importe}\n"
        f"Data de publicação: {fecha}\n"
        f"CPV principal: {_cpv_label(doc.get('cpv'), 'es')}\n"
        f"Local: {localidad}"
    )
    completion = (
        f"Este contrato público espanhol, publicado a {fecha}, tem por objeto {objeto} "
        f"e foi adjudicado por {organo} a {adjudicatario}, por {importe}, através do "
        f"procedimento {procedimiento}. O CPV principal é {_cpv_label(doc.get('cpv'), 'es')}."
    )
    return (
        _truncate(prompt, max_chars) if max_chars else prompt,
        completion,
        {"id_expediente": expediente, "pais": "ES", "ano": doc.get("ano")},
    )


def _build_contrato_fr(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    ident = _clean(doc.get("id"))
    objeto = _truncate(_clean(doc.get("objet")), max_chars)
    if not ident or not objeto:
        return None
    acheteur = _clean(doc.get("acheteur_nom"))
    if not acheteur:
        acheteur_id = _clean(doc.get("acheteur_id"))
        acheteur = f"entidade {acheteur_id}" if acheteur_id else "não identificado"
    titulares = _listed(doc.get("titulaires") or doc.get("adjudicatario_nom"))
    montante = _money(doc.get("montant"))
    data = _clean(doc.get("date_publication")) or "data desconhecida"
    procedimento = _clean(doc.get("procedure")) or "não especificado"
    local = _clean(doc.get("lieu_execution_nom")) or "não especificado"

    prompt = (
        f"Contrat {ident} - {objeto}\n"
        f"Comprador: {acheteur}\n"
        f"Titulares: {titulares}\n"
        f"Natureza: {_clean(doc.get('nature')) or 'não especificada'}\n"
        f"Procedimento: {procedimento}\n"
        f"Montante: {montante}\n"
        f"Data de publicação: {data}\n"
        f"CPV principal: {_cpv_label(doc.get('cpv'), 'fr')}\n"
        f"Local: {local}"
    )
    completion = (
        f"Este contrato público francês, publicado a {data}, tem por objeto {objeto} e foi "
        f"celebrado entre {acheteur} e {titulares}, por {montante}, no âmbito do procedimento "
        f"{procedimento}. O CPV principal é {_cpv_label(doc.get('cpv'), 'fr')}."
    )
    return (
        _truncate(prompt, max_chars) if max_chars else prompt,
        completion,
        {"id": ident, "pais": "FR", "ano": doc.get("ano")},
    )


def _build_entidade(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    nome = _clean(doc.get("name"))
    nif = _clean(doc.get("nif"))
    if not (nome or nif):
        return None
    pais = _clean(doc.get("country") or doc.get("country_code")) or "não especificado"
    total = _num(doc.get("contracts_count"), "um número indeterminado de")
    como_adjudicante = _num(doc.get("as_adjudicante_count"))
    como_adjudicatario = _num(doc.get("as_adjudicatario_count"))
    valor = _money(doc.get("total_value"))
    valor_adjudicante = _money(doc.get("as_adjudicante_value"))

    prompt = (
        f"Entidade: {nome or 'sem nome'}\n"
        f"NIF: {nif or 'não especificado'}\n"
        f"País: {pais}\n"
        f"Contratos registados: {total}\n"
        f"Como adjudicante: {como_adjudicante} contratos ({valor_adjudicante})\n"
        f"Como adjudicatário: {como_adjudicatario} contratos\n"
        f"Valor total: {valor}"
    )
    completion = (
        f"{nome or 'Esta entidade'} (NIF {nif or 'não especificado'}, {pais}) aparece em "
        f"{total} contratos públicos registados: {como_adjudicante} como adjudicante "
        f"({valor_adjudicante}) e {como_adjudicatario} como adjudicatário, num total de {valor}."
    )
    return (
        _truncate(prompt, max_chars) if max_chars else prompt,
        completion,
        {"nif": nif, "name": nome, "country": pais},
    )


def _build_subvencao(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Subsídios públicos (``finance_subvencoes``, do Portal da Transparência).

    Cada registo é uma atribuição: quem dá, quem recebe, quanto, para quê e ao
    abrigo de que norma — dinheiro público a entrar, o espelho dos contratos (que
    é dinheiro a sair).
    """
    beneficiario = _clean(doc.get("beneficiario"))
    montante_raw = doc.get("montante")
    if not beneficiario or montante_raw in (None, ""):
        return None
    entidade = _clean(doc.get("entidade")) or "não identificada"
    nif_beneficiario = _clean(doc.get("nif_beneficiario"))
    nif_entidade = _clean(doc.get("nif_entidade"))
    montante = _money(montante_raw)
    finalidade = _truncate(_clean(doc.get("finalidade")), max_chars) or "não especificada"
    data = _clean(doc.get("data_decisao")) or "data desconhecida"
    base_legal = _truncate(_clean(doc.get("fundamento_legal")), max_chars) or "não especificado"
    tipo_beneficiario = _clean(doc.get("beneficiario_tipo")) or "não especificado"

    prompt = (
        f"Beneficiário: {beneficiario}\n"
        f"NIF do beneficiário: {nif_beneficiario or 'não especificado'}\n"
        f"Tipo de beneficiário: {tipo_beneficiario}\n"
        f"Entidade que atribui: {entidade}\n"
        f"Montante: {montante_raw}\n"
        f"Finalidade: {finalidade}\n"
        f"Data da decisão: {data}\n"
        f"Enquadramento legal: {base_legal}"
    )
    completion = (
        f"O subsídio de {montante}, atribuído por {entidade} a {beneficiario} em {data}, "
        f"teve como finalidade {finalidade}. O enquadramento legal é {base_legal}."
    )
    return (
        _truncate(prompt, max_chars) if max_chars else prompt,
        completion,
        {
            "beneficiario": beneficiario,
            "nif_beneficiario": nif_beneficiario,
            "nif_entidade": nif_entidade,
            "ano": doc.get("ano"),
            "montante": montante_raw,
        },
    )


def _build_noticia(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    titulo = _truncate(_clean(doc.get("title")), max_chars)
    sentimento = _clean(doc.get("sentiment"))
    if not titulo or not sentimento:
        return None
    resumo = _truncate(_clean(doc.get("summary_pt") or doc.get("summary") or doc.get("translated_summary")), max_chars)
    ticker = _clean(doc.get("ticker"))
    editora = _clean(doc.get("publisher"))
    temas = _listed(doc.get("topics"), fallback="não especificados")

    prompt = (
        f"Título: {titulo}\n"
        f"Ticker: {ticker or 'não especificado'}\n"
        f"Editora: {editora or 'não especificada'}\n"
        f"Resumo: {resumo or 'sem resumo'}"
    )
    completion = (
        f"Sentimento: {sentimento}. O tom geral da notícia «{titulo}» é {sentimento}, "
        f"com os temas {temas}."
    )
    return (
        _truncate(prompt, max_chars) if max_chars else prompt,
        completion,
        {"ticker": ticker, "published": doc.get("published"), "publisher": editora},
    )


RECIPES: Dict[str, Recipe] = {
    "contratos": Recipe(
        index=CONTRACTS_INDEX,
        instruction="Descreve este contrato público português.",
        includes=(
            "idcontrato", "objectoContrato", "descContrato", "adjudicantes", "adjudicatarios",
            "tipoContrato", "tipoprocedimento", "precoContratual", "cpv", "dataPublicacao",
            "regime", "Ano",
        ),
        build=_build_contrato_pt_variantes,
    ),
    "contratos-es": Recipe(
        index=CONTRATOS_ES_INDEX,
        instruction="Descreve este contrato público espanhol.",
        includes=(
            "id_expediente", "objeto", "descripcion", "organo_nombre", "adjudicatario_nombre",
            "tipo_contrato_label", "tipo_contrato", "procedimiento_label", "procedimiento",
            "valor_adjudicado", "fecha_publicacion", "cpv", "localidad", "ano",
        ),
        build=_build_contrato_es,
    ),
    "contratos-fr": Recipe(
        index=CONTRATOS_FR_INDEX,
        instruction="Descreve este contrato público francês.",
        includes=(
            "id", "objet", "acheteur_nom", "titulaires", "adjudicatario_nom", "nature",
            "procedure", "montant", "date_publication", "cpv", "lieu_execution_nom", "ano",
        ),
        build=_build_contrato_fr,
    ),
    "empresas": Recipe(
        index=ENTITIES_INDEX,
        instruction="Descreve esta entidade no cadastro de contratos públicos.",
        includes=(
            "nif", "name", "country", "country_code", "contracts_count",
            "as_adjudicante_count", "as_adjudicatario_count", "total_value",
            "as_adjudicante_value",
        ),
        build=_build_entidade,
    ),
    "subvencoes": Recipe(
        index=SUBVENCOES_INDEX,
        instruction="Descreve este subsídio público português.",
        includes=(
            "entidade", "nif_entidade", "beneficiario", "nif_beneficiario",
            "beneficiario_tipo", "montante", "finalidade", "data_decisao", "ano",
            "tipo_ato", "numero_ato", "fundamento_legal",
        ),
        build=_build_subvencao,
        query={
            "bool": {
                "must": [
                    {"exists": {"field": "beneficiario"}},
                    {"exists": {"field": "montante"}},
                ]
            }
        },
    ),
    "noticias": Recipe(
        index=NEWS_INDEX,
        instruction="Classifica o sentimento desta notícia financeira (positivo, negativo ou neutro).",
        includes=("title", "summary", "summary_pt", "translated_summary", "ticker", "publisher", "topics", "sentiment"),
        build=_build_noticia,
        query={"exists": {"field": "sentiment"}},
    ),
}


# ---------------------------------------------------------------------------
# Índices à medida (moldes com {campo})
# ---------------------------------------------------------------------------
class _SafeDict(dict):
    """``str.format_map`` que deixa o marcador intacto quando o campo não existe."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _flatten(doc: Dict[str, Any]) -> Dict[str, str]:
    return {key: _listed(value, fallback="") for key, value in doc.items()}


def _make_custom_builder(
    input_template: str,
    output_template: str,
) -> Callable[[Dict[str, Any], int], Optional[Tuple[str, str, Dict[str, Any]]]]:
    def build(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        values = _flatten(doc)
        prompt = _truncate(input_template.format_map(_SafeDict(values)).strip(), max_chars)
        completion = _truncate(output_template.format_map(_SafeDict(values)).strip(), max_chars)
        if not prompt or not completion:
            return None
        return prompt, completion, {}

    return build


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def _resolve_client(es_url: Optional[str], timeout: int):
    if es_url:
        from elasticsearch import Elasticsearch

        return Elasticsearch(es_url, request_timeout=timeout)
    client = get_es_client(request_timeout=timeout)
    if client is None:
        raise SystemExit(
            "Elasticsearch indisponível. Arranque o serviço (`docker compose up -d elasticsearch`) "
            "ou aponte com --es-url (ou a variável ELASTICSEARCH_URL)."
        )
    return client


def _make_token_counter(tokenizer_path: str) -> Callable[[str], int]:
    """Contador de tokens do modelo de destino (``--tokenizer``).

    O ``soup train`` **recusa** linhas que ficam sem resposta depois da truncagem
    (`data.max_length`), em vez de as saltar — uma única linha comprida aborta a
    corrida. Este contador deixa o exporter medir cada par e não escrever os que
    não cabem na janela do modelo.
    """
    from transformers import AutoTokenizer

    local = Path(tokenizer_path).exists()
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=local)
    cache: Dict[str, int] = {}

    def count(text: str) -> int:
        if text not in cache:
            cache[text] = len(tokenizer.encode(text, add_special_tokens=False))
        return cache[text]

    return count


@dataclass(frozen=True)
class Source:
    """Uma fonte do dataset: que índice ler, com que instrução e como montar o par."""

    index: str
    instruction: str
    includes: Tuple[str, ...]
    builder: Callable[
        [Dict[str, Any], int],
        Union[
            Optional[Tuple[str, str, Dict[str, Any]]],
            Optional[List[Tuple[str, Dict[str, Any], str, Dict[str, Any]]]],
        ],
    ]
    query: Optional[Dict[str, Any]] = None
    label: str = ""

    def nome(self) -> str:
        return self.label or self.index


def _body_for(source: Source, seed: Optional[int]) -> Dict[str, Any]:
    """Corpo da pesquisa de uma fonte, com a amostra dispersa (``--seed``), se pedida."""
    body = source.query or {"match_all": {}}
    if seed is not None:
        # Sem isto, os primeiros N documentos de um índice vêm todos do mesmo
        # ficheiro de origem — um export de `finance_subvencoes` deu 800 registos
        # do mesmo organismo e do mesmo ano.
        body = {
            "function_score": {
                "query": body,
                "random_score": {"seed": seed, "field": "_seq_no"},
            }
        }
    return body


def _stats(por_fonte: List[Dict[str, Any]], *, dry_run: bool = False) -> Dict[str, Any]:
    """Resumo de uma ou várias fontes.

    Com uma só fonte mantém-se a forma plana de sempre (``index``/``matched``/…),
    que é o contrato do CLI e dos testes; com várias, ficam os totais agregados e o
    detalhe por fonte em ``fontes``.
    """
    resumo: Dict[str, Any] = {
        "index": "+".join(fonte["index"] for fonte in por_fonte),
        "matched": sum(fonte["matched"] for fonte in por_fonte),
        "written": sum(fonte["written"] for fonte in por_fonte),
        "skipped": sum(fonte["skipped"] for fonte in por_fonte),
        "dropped": sum(fonte["dropped"] for fonte in por_fonte),
    }
    if len(por_fonte) == 1:
        resumo["index"] = por_fonte[0]["index"]
    else:
        resumo["fontes"] = por_fonte
    if dry_run:
        resumo["dry_run"] = True
    else:
        resumo["read"] = sum(fonte["read"] for fonte in por_fonte)
    return resumo


def export(
    *,
    index: str,
    instruction: str,
    includes: Tuple[str, ...],
    builder: Callable[[Dict[str, Any], int], Optional[Tuple[str, str, Dict[str, Any]]]],
    out_path: Path,
    query: Optional[Dict[str, Any]] = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_chars: int = DEFAULT_MAX_CHARS,
    batch_size: int = 1_000,
    es_url: Optional[str] = None,
    timeout: int = 120,
    dry_run: bool = False,
    count_tokens: Optional[Callable[[str], int]] = None,
    max_tokens: int = 0,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Exporta **uma** fonte — ver :func:`export_many` (é ele que trata das várias)."""
    return export_many(
        sources=[Source(index=index, instruction=instruction, includes=includes, builder=builder, query=query)],
        out_path=out_path,
        max_records=max_records,
        max_chars=max_chars,
        batch_size=batch_size,
        es_url=es_url,
        timeout=timeout,
        dry_run=dry_run,
        count_tokens=count_tokens,
        max_tokens=max_tokens,
        seed=seed,
    )


def export_many(
    *,
    sources: Sequence[Source],
    out_path: Path,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_chars: int = DEFAULT_MAX_CHARS,
    batch_size: int = 1_000,
    es_url: Optional[str] = None,
    timeout: int = 120,
    dry_run: bool = False,
    count_tokens: Optional[Callable[[str], int]] = None,
    max_tokens: int = 0,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Percorre as fontes e escreve um JSONL por par, todas no mesmo ficheiro.

    É o que permite treinar um só modelo sobre várias fontes
    (``--dataset contratos --dataset empresas``): cada fonte é lida por inteiro e o
    teto de ``max_records`` conta por fonte, não pelo total. O destino só é escrito
    no fim (``<out>.tmp`` renomeado), por isso uma falha a meio não deixa um
    dataset truncado a fazer de conta que está bom.

    Com ``count_tokens`` e ``max_tokens``, as linhas cujo prompt + resposta passa
    o orçamento são contadas em ``dropped`` e não escritas — ver
    ``_make_token_counter``. Com ``seed``, os documentos vêm por ordem aleatória
    (amostra dispersa pelo índice) em vez da ordem do índice.
    """
    if not sources:
        raise ValueError("é preciso pelo menos uma fonte")

    client = _resolve_client(es_url, timeout)
    limit = max_records if max_records and max_records > 0 else None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")

    por_fonte: List[Dict[str, Any]] = []
    for source in sources:
        body = _body_for(source, seed)
        if not client.indices.exists(index=source.index):
            raise SystemExit(f"Índice «{source.index}» não existe no Elasticsearch.")
        total = int(client.count(index=source.index, query=body).get("count", 0))
        logger.info("Fonte «%s» (índice «%s»): %d documentos no filtro.", source.nome(), source.index, total)
        por_fonte.append({
            "index": source.index,
            "label": source.nome(),
            "matched": total,
            "read": 0,
            "written": 0,
            "skipped": 0,
            "dropped": 0,
        })

    if dry_run:
        return _stats(por_fonte, dry_run=True)

    from elasticsearch.helpers import scan

    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            for source, contagens in zip(sources, por_fonte):
                for doc in scan(
                    client,
                    index=source.index,
                    query={"query": _body_for(source, seed)},
                    scroll="15m",
                    size=batch_size,
                    request_timeout=timeout,
                    # O `scan` injecta `sort: _doc` (ordem do índice) e isso anularia a
                    # pontuação aleatória do `random_score`. Com `preserve_order` a
                    # ordem passa a ser a da pontuação — que, com a semente, é aleatória.
                    preserve_order=seed is not None,
                    _source_includes=list(source.includes) if source.includes else None,
                ):
                    contagens["read"] += 1
                    built = source.builder(doc.get("_source") or {}, max_chars)
                    if built is None:
                        contagens["skipped"] += 1
                    else:
                        # Um documento pode servir várias instruções: a receita
                        # devolve uma lista de pares em vez de um só.
                        pares = built if isinstance(built, list) else [(source.instruction, *built)]
                        for instruction, prompt, completion, metadata in pares:
                            if count_tokens and max_tokens and count_tokens(prompt) + count_tokens(completion) > max_tokens:
                                contagens["dropped"] += 1
                                continue
                            record = {
                                "instruction": instruction,
                                "input": prompt,
                                "output": completion,
                                "metadata": {**metadata, "index": source.index, "fonte": source.nome()},
                            }
                            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                            contagens["written"] += 1
                            if contagens["written"] % 5_000 == 0:
                                logger.info(
                                    "… %d exemplos escritos (%s: %d de %d lidos)",
                                    sum(fonte["written"] for fonte in por_fonte),
                                    source.nome(), contagens["written"], contagens["read"],
                                )
                    if limit and contagens["read"] >= limit:
                        logger.info("Fonte «%s»: limite de %d documentos lidos atingido.", source.nome(), limit)
                        break
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    tmp_path.replace(out_path)
    stats = _stats(por_fonte)
    logger.info(
        "Guardado %s — %d exemplos de %d fonte(s) (%d lidos, %d sem campos suficientes, %d acima de %s tokens).",
        out_path, stats["written"], len(sources), stats["read"], stats["skipped"], stats["dropped"],
        max_tokens or "∞",
    )
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exporta datasets de fine-tuning (Alpaca) do Elasticsearch para o Soup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dataset", action="append", choices=sorted(RECIPES), metavar="RECEITA",
                        help="Receita a exportar; pode repetir-se (--dataset A --dataset B) para juntar fontes no mesmo ficheiro (ver --list)")
    parser.add_argument("--index", help="Índice à medida (usa --instruction/--input-template/--output-template)")
    parser.add_argument("--instruction", help="Instrução do índice à medida")
    parser.add_argument("--input-template", help="Molde da entrada, com {campo}")
    parser.add_argument("--output-template", help="Molde da resposta, com {campo}")
    parser.add_argument("--fields", help="Campos a ler do índice à medida (lista separada por vírgulas)")
    parser.add_argument("--out", type=Path, help=f"Ficheiro de saída (padrão: {DEFAULT_OUT_DIR}\\<dataset>.jsonl)")
    parser.add_argument("--query", help='Filtro Elasticsearch em JSON, ex.: \'{"term": {"Ano": 2025}}\' (só com uma fonte)')
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS,
                        help=f"Máximo de documentos a ler, 0 = todos (padrão: {DEFAULT_MAX_RECORDS})")
    parser.add_argument("--batch-size", type=int, default=1_000, help="Documentos por pedido ao Elasticsearch")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"Corte por campo, 0 = sem corte (padrão: {DEFAULT_MAX_CHARS})")
    parser.add_argument("--es-url", help="URL do Elasticsearch (padrão: ELASTICSEARCH_URL ou http://127.0.0.1:9200)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout dos pedidos, em segundos")
    parser.add_argument("--tokenizer", help="Tokenizer do modelo de destino, para medir os pares (ex.: model/mistral-finance/final)")
    parser.add_argument("--max-tokens", type=int, default=0,
                        help="Orçamento de tokens por par (prompt + resposta); 0 = sem limite. Exige --tokenizer")
    parser.add_argument("--seed", type=int,
                        help="Amostra dispersa pelo índice com esta semente (sem ele, a ordem do índice agrupa por ficheiro de origem)")
    parser.add_argument("--dry-run", action="store_true", help="Só contar os documentos que correspondem ao filtro")
    parser.add_argument("--list", action="store_true", help="Listar as receitas disponíveis")
    parser.add_argument("--verbose", action="store_true", help="Log detalhado")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list:
        print("Receitas disponíveis:\n")
        for name, recipe in sorted(RECIPES.items()):
            print(f"  {name:<14} {recipe.index:<16} {recipe.instruction}")
        return 0

    query = None
    if args.query:
        try:
            query = json.loads(args.query)
        except json.JSONDecodeError as exc:
            parser.error(f"--query não é JSON válido: {exc}")

    if args.index:
        missing = [flag for flag, value in (
            ("--instruction", args.instruction),
            ("--input-template", args.input_template),
            ("--output-template", args.output_template),
        ) if not value]
        if missing:
            parser.error("com --index são obrigatórios: " + ", ".join(missing))
        includes = tuple(part.strip() for part in (args.fields or "").split(",") if part.strip())
        sources = [Source(
            index=args.index,
            instruction=args.instruction,
            includes=includes,
            builder=_make_custom_builder(args.input_template, args.output_template),
            query=query,
            label=args.index,
        )]
        default_name = f"es_{args.index}"
    elif args.dataset:
        nomes = list(dict.fromkeys(args.dataset))
        if len(nomes) != len(args.dataset):
            parser.error("--dataset repetido: " + ", ".join(sorted(args.dataset)))
        sources = [
            Source(
                index=RECIPES[nome].index,
                instruction=RECIPES[nome].instruction,
                includes=RECIPES[nome].includes,
                builder=RECIPES[nome].build,
                query=RECIPES[nome].query,
                label=nome,
            )
            for nome in nomes
        ]
        if query is not None:
            # Sem receita única não há como decidir a que fonte o filtro se aplica.
            if len(sources) > 1:
                parser.error("--query só se aplica a uma fonte (indique um só --dataset)")
            sources = [replace(sources[0], query=query)]
        default_name = "_".join(nomes)
    else:
        parser.error("indique --dataset (ver --list) ou --index")

    out_path = args.out or (DEFAULT_OUT_DIR / f"{default_name}.jsonl")
    logger.info(
        "A exportar %s para %s",
        ", ".join(f"{source.nome()} ({source.index})" for source in sources),
        out_path,
    )

    if args.max_tokens and not args.tokenizer:
        parser.error("--max-tokens exige --tokenizer (sem tokenizer não há como medir os pares)")
    count_tokens = _make_token_counter(args.tokenizer) if args.tokenizer and args.max_tokens else None
    if count_tokens:
        logger.info("Orçamento de %d tokens por par, medido com %s.", args.max_tokens, args.tokenizer)

    stats = export_many(
        sources=sources,
        out_path=out_path,
        max_records=args.max_records,
        max_chars=args.max_chars,
        batch_size=args.batch_size,
        es_url=args.es_url,
        timeout=args.timeout,
        dry_run=args.dry_run,
        count_tokens=count_tokens,
        max_tokens=args.max_tokens,
        seed=args.seed,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
