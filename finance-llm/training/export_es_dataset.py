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

Índice à medida (sem receita): dá-se a instrução e os moldes de entrada/saída,
com ``{campo}`` substituídos por campos de topo do documento::

    python training/export_es_dataset.py --index finance_news \
        --instruction "Resume esta notícia." \
        --input-template "{title}" --output-template "{summary_pt}" \
        --fields title,summary_pt

O ficheiro é escrito em UTF-8, uma linha por exemplo, e só substitui o destino
no fim — nunca fica um dataset truncado a meio.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import (  # noqa: E402
    CONTRACTS_INDEX,
    CONTRATOS_ES_INDEX,
    CONTRATOS_FR_INDEX,
    ENTITIES_INDEX,
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
    """Colapsa espaços (os documentos trazem quebras de linha e tabulações)."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


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
    build: Callable[[Dict[str, Any], int], Optional[Tuple[str, str, Dict[str, Any]]]]
    query: Dict[str, Any] = field(default_factory=lambda: {"match_all": {}})


def _build_contrato_pt(doc: Dict[str, Any], max_chars: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Espelha ``collectors/contratos.py::build_training_corpus`` (mesma redação)."""
    idcontrato = _clean(doc.get("idcontrato"))
    objecto = _truncate(_clean(doc.get("objectoContrato") or doc.get("descContrato")), max_chars)
    if not idcontrato or not objecto:
        return None
    adjudicante = _listed(doc.get("adjudicantes"), fallback="não identificado")
    adjudicatario = _listed(doc.get("adjudicatarios"), fallback="não identificado")
    tipo = _listed(doc.get("tipoContrato"))
    procedimento = _clean(doc.get("tipoprocedimento")) or "não especificado"
    preco_raw = doc.get("precoContratual")
    preco = _money(preco_raw)
    descricao = _truncate(_clean(doc.get("descContrato")), max_chars)
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
        f"Descrição: {descricao}"
    )
    completion = (
        f"Este contrato, publicado a {data} e com regime {regime}, envolve {objecto} "
        f"entre {adjudicante} e {adjudicatario}. O valor contratual foi {preco} e o "
        f"CPV principal é {cpv}."
    )
    return (
        _truncate(prompt, max_chars) if max_chars else prompt,
        completion,
        {"idcontrato": idcontrato, "ano": doc.get("Ano"), "tipoContrato": doc.get("tipoContrato")},
    )


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
        build=_build_contrato_pt,
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
) -> Dict[str, Any]:
    """Percorre o índice e escreve o JSONL. Devolve as contagens do que foi feito."""
    client = _resolve_client(es_url, timeout)
    body = query or {"match_all": {}}

    if not client.indices.exists(index=index):
        raise SystemExit(f"Índice «{index}» não existe no Elasticsearch.")

    total = int(client.count(index=index, query=body).get("count", 0))
    logger.info("Índice «%s»: %d documentos correspondem ao filtro.", index, total)
    if dry_run:
        return {"index": index, "matched": total, "written": 0, "skipped": 0, "dry_run": True}

    from elasticsearch.helpers import scan

    limit = max_records if max_records and max_records > 0 else None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")

    written = 0
    skipped = 0
    seen = 0
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            for doc in scan(
                client,
                index=index,
                query={"query": body},
                scroll="15m",
                size=batch_size,
                request_timeout=timeout,
                _source_includes=list(includes) if includes else None,
            ):
                seen += 1
                built = builder(doc.get("_source") or {}, max_chars)
                if built is None:
                    skipped += 1
                else:
                    prompt, completion, metadata = built
                    record = {
                        "instruction": instruction,
                        "input": prompt,
                        "output": completion,
                        "metadata": {**metadata, "index": index},
                    }
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    written += 1
                    if written % 5_000 == 0:
                        logger.info("… %d exemplos escritos (%d lidos)", written, seen)
                if limit and seen >= limit:
                    logger.info("Limite de %d documentos lidos atingido.", limit)
                    break
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    tmp_path.replace(out_path)
    stats = {"index": index, "matched": total, "read": seen, "written": written, "skipped": skipped}
    logger.info(
        "Guardado %s — %d exemplos (%d lidos, %d sem campos suficientes).",
        out_path, written, seen, skipped,
    )
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exporta datasets de fine-tuning (Alpaca) do Elasticsearch para o Soup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dataset", choices=sorted(RECIPES), help="Receita a exportar")
    parser.add_argument("--index", help="Índice à medida (usa --instruction/--input-template/--output-template)")
    parser.add_argument("--instruction", help="Instrução do índice à medida")
    parser.add_argument("--input-template", help="Molde da entrada, com {campo}")
    parser.add_argument("--output-template", help="Molde da resposta, com {campo}")
    parser.add_argument("--fields", help="Campos a ler do índice à medida (lista separada por vírgulas)")
    parser.add_argument("--out", type=Path, help=f"Ficheiro de saída (padrão: {DEFAULT_OUT_DIR}\\<dataset>.jsonl)")
    parser.add_argument("--query", help='Filtro Elasticsearch em JSON, ex.: \'{"term": {"Ano": 2025}}\'')
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS,
                        help=f"Máximo de documentos a ler, 0 = todos (padrão: {DEFAULT_MAX_RECORDS})")
    parser.add_argument("--batch-size", type=int, default=1_000, help="Documentos por pedido ao Elasticsearch")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"Corte por campo, 0 = sem corte (padrão: {DEFAULT_MAX_CHARS})")
    parser.add_argument("--es-url", help="URL do Elasticsearch (padrão: ELASTICSEARCH_URL ou http://127.0.0.1:9200)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout dos pedidos, em segundos")
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

    if args.index:
        missing = [flag for flag, value in (
            ("--instruction", args.instruction),
            ("--input-template", args.input_template),
            ("--output-template", args.output_template),
        ) if not value]
        if missing:
            parser.error("com --index são obrigatórios: " + ", ".join(missing))
        index = args.index
        includes = tuple(part.strip() for part in (args.fields or "").split(",") if part.strip())
        instruction = args.instruction
        builder = _make_custom_builder(args.input_template, args.output_template)
        default_name = f"es_{index}"
    elif args.dataset:
        recipe = RECIPES[args.dataset]
        index = recipe.index
        includes = recipe.includes
        instruction = recipe.instruction
        builder = recipe.build
        default_name = args.dataset
        if args.query is None and recipe.query is not None:
            args.query = json.dumps(recipe.query)
    else:
        parser.error("indique --dataset (ver --list) ou --index")

    query = None
    if args.query:
        try:
            query = json.loads(args.query)
        except json.JSONDecodeError as exc:
            parser.error(f"--query não é JSON válido: {exc}")

    out_path = args.out or (DEFAULT_OUT_DIR / f"{default_name}.jsonl")
    logger.info("A exportar «%s» (%s) para %s", default_name, index, out_path)

    stats = export(
        index=index,
        instruction=instruction,
        includes=includes,
        builder=builder,
        out_path=out_path,
        query=query,
        max_records=args.max_records,
        max_chars=args.max_chars,
        batch_size=args.batch_size,
        es_url=args.es_url,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
