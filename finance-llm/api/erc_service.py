"""Recolha, normalização, indexação e pesquisa do **Portal da Transparência da ERC**.

O portal (`portaltransparencia.erc.pt`) publica as **entidades proprietárias de
órgãos de comunicação social** (OCS), as **pessoas** dos seus órgãos sociais, os
**OCS detidos** e a estrutura de propriedade (quem detém quem). Este módulo:

1. lê a listagem completa de entidades (`/entidades-ocs/?idActividade=all`);
2. abre a ficha de cada entidade — dados gerais, pessoas dos órgãos sociais,
   OCS detidos e estrutura de propriedade (detentores/detidas, por API);
3. guarda cada pessoa referida e abre-lhe a ficha — cargos (órgãos sociais) e
   participações diretas;
4. persiste tudo em JSONL (`data/erc/*.jsonl`) e indexa em três índices do
   Elasticsearch (`finance_erc_entidades`, `finance_erc_pessoas`,
   `finance_erc_ocs`), com o histórico das recolhas em `finance_erc_recolhas`.

O trabalho é pesado (o portal tem ~1.400 entidades e vários pedidos por ficha),
por isso a recolha corre em segundo plano e aceita um `limite` — útil para
amostras e para retomar sem repetir o que já está em disco.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from api import erc_risco
from collectors import erc_transparencia as erc
from collectors.erc_transparencia import (
    parse_entity_geral,
    parse_entity_ocs,
    parse_entity_orgs,
    parse_entity_tabs,
    parse_financeiro_anos,
    parse_listing,
    parse_person_geral,
    parse_person_orgs,
    parse_person_tabs,
)

logger = logging.getLogger(__name__)

#: Pausa entre pedidos ao portal (cortesia com a infraestrutura pública).
PAUSA_PADRAO = float(os.getenv("ERC_PAUSA", "0.4"))
#: Tentativas por pedido antes de registar erro.
TENTATIVAS = int(os.getenv("ERC_TENTATIVAS", "3"))
#: Teto do HTML guardado por página (o portal serve ~600 KB na listagem).
MAX_HTML_BYTES = 4 * 1024 * 1024
#: Validade da listagem em cache (uma listagem nova muda de dia para dia).
CACHE_TTL_SEGUNDOS = int(os.getenv("ERC_CACHE_TTL", str(24 * 60 * 60)))
#: Itens recolhidos antes de gravar o lote em disco (retomada + menos escrita).
LOTE_FLUSH = int(os.getenv("ERC_LOTE_FLUSH", "20"))

DEFAULT_DATA_DIR = Path(
    os.getenv("ERC_DATA_DIR") or (Path(__file__).resolve().parents[1] / "data" / "erc")
)
FONTE = "erc-transparencia"

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 20
_RUNNING = "running"

TIPOS_JOB = ("recolher", "recolher_financeiro", "analisar", "indexar")

_ESPACOS = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def data_dir() -> Path:
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_DATA_DIR


def raw_dir() -> Path:
    path = data_dir() / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def entidades_jsonl() -> Path:
    return data_dir() / "entidades.jsonl"


def pessoas_jsonl() -> Path:
    return data_dir() / "pessoas.jsonl"


def ocs_jsonl() -> Path:
    return data_dir() / "ocs.jsonl"


def recolhas_jsonl() -> Path:
    return data_dir() / "recolhas.jsonl"


def listagem_json() -> Path:
    return data_dir() / "listagem.json"


def _slug(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return _ESPACOS.sub("-", re.sub(r"[^a-zA-Z0-9]+", " ", texto).strip().lower()) or "sem-nome"


def _iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for linha in handle:
            linha = linha.strip()
            if not linha:
                continue
            try:
                yield json.loads(linha)
            except json.JSONDecodeError:
                continue


def _merge_jsonl(path: Path, docs: Iterable[Dict[str, Any]], *, chaves: Tuple[str, ...] = ("doc_id",)) -> int:
    """Faz *upsert* dos documentos no JSONL (por `chaves`) e devolve o total."""
    atuais: Dict[str, Dict[str, Any]] = {}
    for item in _iter_jsonl(path):
        key = _key_of(item, chaves)
        if key:
            atuais[key] = item
    for doc in docs:
        key = _key_of(doc, chaves)
        if key:
            atuais[key] = doc
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for key in sorted(atuais):
            handle.write(json.dumps(atuais[key], ensure_ascii=False) + "\n")
    tmp.replace(path)
    return len(atuais)


def _key_of(item: Dict[str, Any], chaves: Tuple[str, ...]) -> Optional[str]:
    partes = [str(item.get(chave) or "").strip() for chave in chaves]
    if not all(partes):
        return None
    return ":".join(partes)


def _append_jsonl(path: Path, items: Iterable[Dict[str, Any]]) -> int:
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            count += 1
    return count


def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _guardar_html(nome: str, html: str) -> Optional[str]:
    """Guarda o HTML em `data/erc/raw/<nome>.html` (devolve o caminho relativo)."""
    dados = html.encode("utf-8", errors="replace")
    if len(dados) > MAX_HTML_BYTES:
        return None
    caminho = raw_dir() / f"{nome}.html"
    try:
        caminho.write_bytes(dados)
    except OSError as exc:
        logger.debug("Não foi possível guardar o HTML de %s: %s", nome, exc)
        return None
    return str(caminho.relative_to(data_dir()))


# ---------------------------------------------------------------------------
# Listagem de entidades (com cache em disco)
# ---------------------------------------------------------------------------

def ler_listagem(*, forcar: bool = False, progresso: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Entidades proprietárias de OCS (listagem completa, com cache em disco)."""
    caminho = listagem_json()
    if not forcar and caminho.exists():
        try:
            cached = json.loads(caminho.read_text(encoding="utf-8"))
            recolhido = cached.get("cached_at") or ""
            dt = datetime.fromisoformat(recolhido.replace("Z", "+00:00"))
            idade = (datetime.now(timezone.utc) - dt).total_seconds()
            itens = cached.get("entidades") or []
            if itens and idade <= CACHE_TTL_SEGUNDOS:
                if progresso is not None:
                    progresso["listagem_em_cache"] = True
                return itens
        except Exception as exc:  # noqa: BLE001 - uma cache inválida é só ignorada
            logger.debug("Listagem em cache inválida: %s", exc)

    with erc.make_client() as client:
        html = erc.fetch_text(client, f"{erc.BASE_URL}{erc.LISTING_PATH}", params=erc.LISTING_PARAMS)
    entidades = parse_listing(html)
    if not entidades:
        raise RuntimeError("A listagem do portal da ERC não devolveu entidades.")
    _guardar_html("listagem", html)
    caminho.write_text(
        json.dumps({"cached_at": _now(), "total": len(entidades), "entidades": entidades}, ensure_ascii=False),
        encoding="utf-8",
    )
    if progresso is not None:
        progresso["listagem_em_cache"] = False
    return entidades


def _registar_recolha_doc(item: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(item)
    doc.setdefault("recolha_id", uuid.uuid4().hex[:12])
    doc.setdefault("recolhido_em", _now())
    doc.setdefault("ingested_at", doc["recolhido_em"])
    doc.setdefault("fonte", FONTE)
    return doc


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------

def _ficha_entidade(
    client: Any,
    item: Dict[str, Any],
    *,
    pausa: float,
    com_estrutura: bool,
    com_financeiro: bool,
    guardar_html: bool,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Lê a ficha de uma entidade.

    Devolve ``(documento, pessoas, documentos de OCS, entradas de recolha)``. As
    recolhas são devolvidas (e não escritas num acumulador partilhado) para a
    leitura poder correr em paralelo sem estado partilhado.
    """
    entidade_id = item["id"]
    slug = item.get("slug") or _slug(item.get("nome"))
    url = f"{erc.BASE_URL}{erc.ENTIDADES_PATH}{slug}/?IdEntidade={entidade_id}"
    recolhido_em = _now()
    recolhas: List[Dict[str, Any]] = []

    def _pedido(secao: str) -> str:
        return client.get(url, params={"IdEntidade": entidade_id, "geral": secao}).text

    geral_html = _pedido("geral")
    geral = parse_entity_geral(geral_html)
    tabs = parse_entity_tabs(geral_html)
    if guardar_html:
        _guardar_html(f"entidade-{entidade_id}-geral", geral_html)
    recolhas.append(_registar_recolha_doc({
        "tipo": "entidade", "entidade_id": entidade_id, "nome": item.get("nome"),
        "url": url, "sha256": _sha256(geral_html.encode("utf-8", errors="replace")),
        "bytes": len(geral_html.encode("utf-8", errors="replace")), "itens": 1,
    }))

    orgs: List[Dict[str, Any]] = []
    if not tabs or "orgs" in tabs:
        time.sleep(pausa)
        orgs_html = _pedido("orgs")
        orgs = parse_entity_orgs(orgs_html)
        if guardar_html:
            _guardar_html(f"entidade-{entidade_id}-orgs", orgs_html)
        recolhas.append(_registar_recolha_doc({
            "tipo": "entidade", "entidade_id": entidade_id, "nome": item.get("nome"),
            "url": url, "sha256": _sha256(orgs_html.encode("utf-8", errors="replace")),
            "bytes": len(orgs_html.encode("utf-8", errors="replace")), "itens": len(orgs),
        }))

    ocs: List[Dict[str, Any]] = []
    if not tabs or "ocs" in tabs:
        time.sleep(pausa)
        ocs_html = _pedido("ocs")
        ocs = parse_entity_ocs(ocs_html)
        if guardar_html:
            _guardar_html(f"entidade-{entidade_id}-ocs", ocs_html)
        recolhas.append(_registar_recolha_doc({
            "tipo": "entidade", "entidade_id": entidade_id, "nome": item.get("nome"),
            "url": url, "sha256": _sha256(ocs_html.encode("utf-8", errors="replace")),
            "bytes": len(ocs_html.encode("utf-8", errors="replace")), "itens": len(ocs),
        }))

    detentores: List[Dict[str, Any]] = []
    detidas: List[Dict[str, Any]] = []
    if com_estrutura:
        time.sleep(pausa)
        try:
            detentores, detidas = erc.fetch_estrutura(client, entidade_id)
        except Exception as exc:  # noqa: BLE001 - a estrutura é complementar
            logger.warning("Estrutura de %s falhou: %s", entidade_id, exc)

    financeiro: List[Dict[str, Any]] = []
    if com_financeiro:
        time.sleep(pausa)
        try:
            anos_html = client.get(url, params={"IdEntidade": entidade_id, "geral": "dafin"}).text
            for ano in parse_financeiro_anos(anos_html):
                time.sleep(pausa)
                financeiro.extend(erc.fetch_financeiro(client, entidade_id, ano))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Dados financeiros de %s falharam: %s", entidade_id, exc)

    doc = {
        "doc_id": entidade_id,
        "nome": geral.get("nome") or item.get("nome"),
        "slug": slug,
        "url": url,
        "tipo_sociedade": geral.get("tipo_sociedade") or item.get("tipo_sociedade"),
        "actividade_principal": geral.get("actividade_principal") or item.get("actividade_principal"),
        "distrito": geral.get("distrito") or item.get("distrito"),
        "contabilidade_organizada": geral.get("contabilidade_organizada"),
        "detem_ocs": geral.get("detem_ocs"),
        "capital_social": geral.get("capital_social"),
        "capital_social_eur": erc.parse_money(geral.get("capital_social")),
        "nr_registo": geral.get("nr_registo"),
        "n_ocs": len(ocs),
        "n_pessoas": len(orgs),
        "n_detentores": len(detentores),
        "n_detidas": len(detidas),
        "pessoas": orgs,
        "pessoas_nomes": sorted({p["nome"] for p in orgs if p.get("nome")}),
        "ocs": ocs,
        "ocs_designacoes": sorted({o["designacao"] for o in ocs if o.get("designacao")}),
        "detentores": detentores,
        "detidas": detidas,
        "financeiro": financeiro,
        "fonte": FONTE,
        "recolhido_em": recolhido_em,
    }
    doc["nome_keyword"] = (doc["nome"] or "").strip()
    doc["distrito_keyword"] = (doc["distrito"] or "").strip()
    return doc, orgs, ocs, recolhas


def _ficha_pessoa(
    client: Any,
    pessoa: Dict[str, Any],
    *,
    pausa: float,
    guardar_html: bool,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Lê a ficha de uma pessoa regulada (dados gerais, cargos e participações).

    Devolve ``(documento, entradas de recolha)``.
    """
    pessoa_id = pessoa["id"]
    nome = pessoa.get("nome")
    url = f"{erc.BASE_URL}{erc.PESSOAS_PATH}"
    recolhido_em = _now()
    recolhas: List[Dict[str, Any]] = []

    def _pedido(secao: str) -> str:
        return client.get(url, params={"idEntidade": pessoa_id, "geral": secao}).text

    geral_html = _pedido("geral")
    geral = parse_person_geral(geral_html)
    tabs = parse_person_tabs(geral_html)
    if guardar_html:
        _guardar_html(f"pessoa-{pessoa_id}-geral", geral_html)
    recolhas.append(_registar_recolha_doc({
        "tipo": "pessoa", "entidade_id": pessoa_id, "nome": nome, "url": url,
        "sha256": _sha256(geral_html.encode("utf-8", errors="replace")),
        "bytes": len(geral_html.encode("utf-8", errors="replace")), "itens": 1,
    }))

    orgaos: List[Dict[str, Any]] = []
    if not tabs or "orgs" in tabs:
        time.sleep(pausa)
        orgaos_html = _pedido("orgs")
        orgaos = parse_person_orgs(orgaos_html)
        if guardar_html:
            _guardar_html(f"pessoa-{pessoa_id}-orgs", orgaos_html)

    participacoes: List[Dict[str, Any]] = []
    if not tabs or "part" in tabs:
        time.sleep(pausa)
        try:
            participacoes = erc.fetch_participacoes(client, pessoa_id, geral.get("nome") or nome)
        except Exception as exc:  # noqa: BLE001 - as participações são complementares
            logger.warning("Participações de %s (%s) falharam: %s", nome, pessoa_id, exc)

    doc = {
        "doc_id": pessoa_id,
        "nome": geral.get("nome") or nome,
        "slug": _slug(geral.get("nome") or nome),
        "url": f"{url}?idEntidade={pessoa_id}",
        "actividade_principal": geral.get("actividade_principal"),
        "distrito": geral.get("distrito"),
        "detem_ocs": geral.get("detem_ocs"),
        "n_empresas": len(orgaos),
        "n_participacoes": len(participacoes),
        "orgaos": orgaos,
        "empresas": sorted({o["nome"] for o in orgaos if o.get("nome")}),
        "participacoes": participacoes,
        "participacoes_nomes": sorted({p["nome"] for p in participacoes if p.get("nome")}),
        "fonte": FONTE,
        "recolhido_em": recolhido_em,
    }
    doc["nome_keyword"] = (doc["nome"] or "").strip()
    doc["distrito_keyword"] = (doc["distrito"] or "").strip()
    return doc, recolhas


def _doc_ocs(entidade: Dict[str, Any], item: Dict[str, Any], recolhido_em: str) -> Dict[str, Any]:
    designacao = item.get("designacao") or ""
    entidade_id = entidade["doc_id"]
    return {
        "doc_id": f"{entidade_id}:{_slug(designacao)}:{_slug(item.get('tipo'))}",
        "designacao": designacao,
        "designacao_keyword": designacao.strip(),
        "tipo": item.get("tipo"),
        "entidade_proprietaria": item.get("entidade_proprietaria") or entidade.get("nome"),
        "entidade_proprietaria_id": entidade_id,
        "distrito": item.get("distrito") or entidade.get("distrito"),
        "distrito_keyword": (item.get("distrito") or entidade.get("distrito") or "").strip(),
        "fonte": FONTE,
        "recolhido_em": recolhido_em,
    }


def recolher(
    *,
    limite: Optional[int] = None,
    pausa: float = PAUSA_PADRAO,
    com_pessoas: bool = True,
    com_estrutura: bool = True,
    com_ocs: bool = True,
    com_financeiro: bool = False,
    guardar_html: bool = True,
    forcar: bool = False,
    saltar_existentes: bool = False,
    trabalhadores: int = 1,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recolhe o portal da ERC: entidades, pessoas dos órgãos sociais e OCS.

    `limite` corta a listagem (amostras e execuções faseadas); `forcar` relê a
    listagem em vez de usar a cache; `saltar_existentes` ignora as entidades que
    já estão em `entidades.jsonl` (retoma sem repetir o que já foi lido, o que
    torna uma paragem a meio inofensiva); `trabalhadores` abre mais do que um
    pedido em paralelo (o portal é público: 1 é o mais cortês, 3 já reduz a
    recolha completa de horas para uma fração do tempo).

    O resultado é guardado por *upsert* nos JSONL do módulo, para uma nova
    execução não duplicar nem perder o já lido.
    """
    progresso = progresso if progresso is not None else {}
    trabalhadores = max(1, min(int(trabalhadores or 1), 8))
    erros: List[str] = []

    progresso["phase"] = "a ler a listagem"
    entidades = ler_listagem(forcar=forcar, progresso=progresso)
    selecionadas = entidades[: int(limite)] if limite else entidades
    if saltar_existentes:
        feitas = {str(doc.get("doc_id") or "") for doc in _iter_jsonl(entidades_jsonl())}
        antes = len(selecionadas)
        selecionadas = [item for item in selecionadas if str(item.get("id")) not in feitas]
        progresso["saltadas"] = antes - len(selecionadas)
    progresso["entidades_total"] = len(selecionadas)
    progresso["entidades_done"] = 0

    pessoas: Dict[str, Dict[str, Any]] = {}
    # Lote em curso: gravado a cada `LOTE_FLUSH` itens (e no fim), para a recolha
    # poder retomar sem perder o que já leu nem reescrever o JSONL item a item.
    _pendentes: Dict[str, List[Dict[str, Any]]] = {"entidades": [], "pessoas": [], "ocs": [], "recolhas": []}

    with erc.make_client() as client:
        progresso["phase"] = "a ler as entidades"

        def _entidade(item: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
            return _ficha_entidade(
                client,
                item,
                pausa=pausa,
                com_estrutura=com_estrutura,
                com_financeiro=com_financeiro,
                guardar_html=guardar_html,
            )

        feitas = 0
        for item, resultado in _em_paralelo(_entidade, selecionadas, trabalhadores):
            feitas += 1
            progresso["entidades_done"] = feitas
            progresso["current"] = item.get("nome")
            if isinstance(resultado, Exception):
                logger.warning("Entidade %s falhou: %s", item.get("id"), resultado)
                erros.append(f"entidade {item.get('id')}: {resultado}")
                _pendentes["recolhas"].append(_registar_recolha_doc({
                    "tipo": "entidade", "entidade_id": item.get("id"), "nome": item.get("nome"), "erro": str(resultado),
                }))
            else:
                doc, orgs, ocs, recolhas_item = resultado
                _pendentes["entidades"].append(doc)
                _pendentes["recolhas"].extend(recolhas_item)
                if com_ocs:
                    _pendentes["ocs"].extend(_doc_ocs(doc, ocs_item, doc["recolhido_em"]) for ocs_item in ocs)
                if com_pessoas:
                    for pessoa in erc.iter_pessoas(orgs):
                        pessoas.setdefault(pessoa["id"], pessoa)
            progresso["registos"] = feitas
            if feitas % LOTE_FLUSH == 0 or feitas == len(selecionadas):
                _flush(_pendentes["entidades"], _pendentes["ocs"], _pendentes["pessoas"], _pendentes["recolhas"])
                for lista in _pendentes.values():
                    lista.clear()

        progresso["phase"] = "a ler as fichas das pessoas"
        pessoas_ordenadas = sorted(pessoas.values(), key=lambda p: str(p.get("nome") or ""))
        progresso["pessoas_total"] = len(pessoas_ordenadas)
        progresso["pessoas_done"] = 0

        def _pessoa(pessoa: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
            return _ficha_pessoa(client, pessoa, pausa=pausa, guardar_html=guardar_html)

        feitas = 0
        for pessoa, resultado in _em_paralelo(_pessoa, pessoas_ordenadas, trabalhadores):
            feitas += 1
            progresso["pessoas_done"] = feitas
            progresso["current"] = pessoa.get("nome")
            if isinstance(resultado, Exception):
                logger.warning("Pessoa %s (%s) falhou: %s", pessoa.get("nome"), pessoa.get("id"), resultado)
                erros.append(f"pessoa {pessoa.get('id')}: {resultado}")
                _pendentes["recolhas"].append(_registar_recolha_doc({
                    "tipo": "pessoa", "entidade_id": pessoa.get("id"), "nome": pessoa.get("nome"), "erro": str(resultado),
                }))
            else:
                doc_pessoa, recolhas_item = resultado
                _pendentes["pessoas"].append(doc_pessoa)
                _pendentes["recolhas"].extend(recolhas_item)
            progresso["registos"] = feitas
            if feitas % LOTE_FLUSH == 0 or feitas == len(pessoas_ordenadas):
                _flush(_pendentes["entidades"], _pendentes["ocs"], _pendentes["pessoas"], _pendentes["recolhas"])
                for lista in _pendentes.values():
                    lista.clear()

    # O que ficou no lote em curso (menos de `LOTE_FLUSH` itens).
    _flush(_pendentes["entidades"], _pendentes["ocs"], _pendentes["pessoas"], _pendentes["recolhas"])
    for lista in _pendentes.values():
        lista.clear()

    progresso["phase"] = "concluído"
    progresso["current"] = None
    total_entidades = len(list(_iter_jsonl(entidades_jsonl())))
    total_pessoas = len(list(_iter_jsonl(pessoas_jsonl())))
    total_ocs = len(list(_iter_jsonl(ocs_jsonl())))
    return {
        "fonte": FONTE,
        "entidades": total_entidades,
        "pessoas": total_pessoas,
        "ocs": total_ocs,
        "recolhidas_agora": {
            "entidades": progresso.get("entidades_done", 0),
            "pessoas": progresso.get("pessoas_done", 0),
            "saltadas": progresso.get("saltadas", 0),
        },
        "trabalhadores": trabalhadores,
        "errors": erros,
        "data_dir": str(data_dir()),
    }


#: Exercícios sondados por omissão na recolha financeira (os mais recentes).
ANOS_FINANCEIRO_JANELA = int(os.getenv("ERC_ANOS_FINANCEIRO", "4"))


def anos_a_varrer(ano_inicio: Optional[int] = None, ano_fim: Optional[int] = None) -> List[int]:
    """Exercícios a sondar, do mais recente para o mais antigo.

    O portal não publica a lista de exercícios de uma entidade (o `select` da
    secção só traz o ano pedido), por isso a janela é varrida ano a ano. Por
    omissão vai até ao exercício anterior ao corrente.
    """
    fim = int(ano_fim) if ano_fim else datetime.now(timezone.utc).year - 1
    inicio = int(ano_inicio) if ano_inicio else fim - ANOS_FINANCEIRO_JANELA + 1
    if inicio > fim:
        inicio, fim = fim, inicio
    return list(range(fim, inicio - 1, -1))


def recolher_financeiro(
    *,
    limite: Optional[int] = None,
    ano_inicio: Optional[int] = None,
    ano_fim: Optional[int] = None,
    vazios_seguidos: int = 0,
    pausa: float = PAUSA_PADRAO,
    trabalhadores: int = 8,
    apenas_sem_financeiro: bool = True,
    guardar_html: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recolhe a secção financeira (`geral=dafin`) das entidades já em disco.

    Cada exercício custa um pedido à API (`GetDadosFinanceira`), que só responde
    a ano a ano: a janela é varrida toda e os anos sem publicação devolvem vazio.
    `vazios_seguidos` corta o varrimento depois de N anos vazios consecutivos
    (0 = varrer a janela inteira) — útil para estender o histórico para trás sem
    pagar os anos vazios.

    Os documentos são fundidos com o que já existe (`financeiro` por ano) e a
    análise de risco é recalculada na mesma passagem.
    """
    progresso = progresso if progresso is not None else {}
    trabalhadores = max(1, min(int(trabalhadores or 1), 16))
    anos = anos_a_varrer(ano_inicio, ano_fim)
    erros: List[str] = []

    docs = list(_iter_jsonl(entidades_jsonl()))
    if not docs:
        raise RuntimeError("Não há entidades em disco: corra primeiro a recolha principal (POST /erc/recolher).")
    alvos = [doc for doc in docs if not (doc.get("financeiro") or [])] if apenas_sem_financeiro else list(docs)
    if limite:
        alvos = alvos[: int(limite)]
    progresso["phase"] = "a ler os dados financeiros"
    progresso["entidades_total"] = len(alvos)
    progresso["entidades_done"] = 0
    progresso["anos"] = anos
    progresso["registos"] = 0

    pendentes: List[Dict[str, Any]] = []
    recolhas_pendentes: List[Dict[str, Any]] = []
    com_dados = 0

    with erc.make_client() as client:

        def _financeira(doc: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
            entidade_id = doc["doc_id"]
            serie: List[Dict[str, Any]] = []
            recolhas: List[Dict[str, Any]] = []
            vazios = 0
            for ano in anos:
                time.sleep(pausa)
                dados = erc.fetch_financeiro(client, entidade_id, ano)
                if not dados:
                    vazios += 1
                    if vazios_seguidos and serie and vazios >= vazios_seguidos:
                        break
                    continue
                vazios = 0
                for item in dados:
                    serie.append(item)
                    recolhas.append(_registar_recolha_doc({
                        "tipo": "financeiro", "entidade_id": entidade_id, "nome": doc.get("nome"), "ano": item.get("ano"),
                        "url": f"{erc.BASE_URL}{erc.API_FINANCEIRA}",
                        "sha256": _sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")),
                        "bytes": len(json.dumps(item, ensure_ascii=False).encode("utf-8")), "itens": 1,
                    }))
            return serie, recolhas

        feitas = 0
        for doc, resultado in _em_paralelo(_financeira, alvos, trabalhadores):
            feitas += 1
            progresso["entidades_done"] = feitas
            progresso["current"] = doc.get("nome")
            if isinstance(resultado, Exception):
                logger.warning("Dados financeiros de %s falharam: %s", doc.get("doc_id"), resultado)
                erros.append(f"financeiro {doc.get('doc_id')}: {resultado}")
            else:
                serie, recolhas = resultado
                if serie:
                    com_dados += 1
                    antigos = {int(item["ano"]): item for item in (doc.get("financeiro") or []) if item.get("ano")}
                    pedidos = {int(item["ano"]): item for item in serie if item.get("ano")}
                    fundido = [*pedidos.values(), *[v for k, v in antigos.items() if k not in pedidos]]
                    pendentes.append(erc_risco.aplicar({**doc, "financeiro": fundido}))
                    recolhas_pendentes.extend(recolhas)
            progresso["registos"] = len(pendentes)
            progresso["com_dados"] = com_dados
            if feitas % LOTE_FLUSH == 0 or feitas == len(alvos):
                if pendentes:
                    _merge_jsonl(entidades_jsonl(), pendentes, chaves=("doc_id",))
                    pendentes.clear()
                if recolhas_pendentes:
                    _append_jsonl(recolhas_jsonl(), recolhas_pendentes)
                    recolhas_pendentes.clear()

    progresso["phase"] = "a recalcular a análise de risco"
    analise = recalcular_analises(progresso=progresso)
    progresso["phase"] = "concluído"
    progresso["current"] = None
    return {
        "fonte": FONTE,
        "anos": {"inicio": anos[-1], "fim": anos[0], "total": len(anos)},
        "varridas": progresso.get("entidades_done", 0),
        "com_dados": com_dados,
        "pessoas": len(list(_iter_jsonl(pessoas_jsonl()))),
        "ocs": len(list(_iter_jsonl(ocs_jsonl()))),
        "analise": analise,
        "trabalhadores": trabalhadores,
        "errors": erros,
        "data_dir": str(data_dir()),
    }


def recalcular_analises(*, progresso: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Recalcula o resumo financeiro e a análise de risco de todas as entidades.

    Não vai ao portal: parte dos JSONL e reescreve-os. Serve para pontuar
    entidades que já tinham dados financeiros antes de a análise existir, e para
    afinar pesos sem repetir a recolha.
    """
    progresso = progresso if progresso is not None else {}
    docs = [erc_risco.aplicar(doc) for doc in _iter_jsonl(entidades_jsonl())]
    if docs:
        _merge_jsonl(entidades_jsonl(), docs, chaves=("doc_id",))
    bandas: Dict[str, int] = {}
    transparencias: Dict[str, int] = {}
    com_credito = 0
    for doc in docs:
        analise = doc.get("analise") or {}
        banda = str((analise.get("risco") or {}).get("banda") or "sem dados")
        bandas[banda] = bandas.get(banda, 0) + 1
        nivel = str((analise.get("transparencia") or {}).get("nivel") or "sem dados")
        transparencias[nivel] = transparencias.get(nivel, 0) + 1
        if (analise.get("credito") or {}).get("disponivel"):
            com_credito += 1
    return {
        "entidades": len(docs),
        "com_dados_financeiros": sum(1 for doc in docs if doc.get("n_anos_financeiro")),
        "com_credito": com_credito,
        "por_banda": dict(sorted(bandas.items(), key=lambda kv: -kv[1])),
        "por_nivel_transparencia": dict(sorted(transparencias.items(), key=lambda kv: -kv[1])),
        "atualizado_em": _now(),
    }


def _em_paralelo(
    funcao: Any,
    itens: List[Dict[str, Any]],
    trabalhadores: int,
) -> Iterator[Tuple[Dict[str, Any], Any]]:
    """Aplica `funcao` a cada item, devolvendo `(item, resultado|exceção)`.

    Com um trabalhador corre em série (mantém a ordem); com mais, usa um
    `ThreadPoolExecutor` e devolve à medida que cada pedido termina.
    """
    if trabalhadores <= 1:
        for item in itens:
            try:
                yield item, funcao(item)
            except Exception as exc:  # noqa: BLE001 - o erro é reportado ao chamador
                yield item, exc
        return
    with ThreadPoolExecutor(max_workers=trabalhadores, thread_name_prefix="erc") as pool:
        futuros = {pool.submit(funcao, item): item for item in itens}
        for futuro in as_completed(futuros):
            item = futuros[futuro]
            try:
                yield item, futuro.result()
            except Exception as exc:  # noqa: BLE001
                yield item, exc


def _flush(
    entidades: List[Dict[str, Any]],
    ocs: List[Dict[str, Any]],
    pessoas: List[Dict[str, Any]],
    recolhas: List[Dict[str, Any]],
) -> None:
    """Aplica em disco o que foi recolhido neste lote (para poder retomar)."""
    for docs, path, chaves in (
        (entidades, entidades_jsonl(), ("doc_id",)),
        (pessoas, pessoas_jsonl(), ("doc_id",)),
        (ocs, ocs_jsonl(), ("doc_id",)),
    ):
        if docs:
            _merge_jsonl(path, docs, chaves=chaves)
    if recolhas:
        _append_jsonl(recolhas_jsonl(), recolhas)


# ---------------------------------------------------------------------------
# Indexação
# ---------------------------------------------------------------------------

def indexar(
    *,
    forcar: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Indexa os JSONL do módulo nos índices `finance_erc_*`.

    `forcar` recria os índices antes de indexar (apaga e volta a criar), o que é
    necessário quando o *mapping* muda: o Elasticsearch não deixa alterar o tipo
    de um campo já criado e os dados vêm sempre dos JSONL.
    """
    from api.elasticsearch_client import (
        ERC_ENTIDADES_INDEX,
        ERC_OCS_INDEX,
        ERC_PESSOAS_INDEX,
        ERC_RECOLHAS_INDEX,
        index_erc_bulk,
    )

    progresso = progresso if progresso is not None else {}
    saida: Dict[str, Any] = {}
    erros: List[str] = []

    for chave, path, index in (
        ("entidades", entidades_jsonl(), ERC_ENTIDADES_INDEX),
        ("pessoas", pessoas_jsonl(), ERC_PESSOAS_INDEX),
        ("ocs", ocs_jsonl(), ERC_OCS_INDEX),
        ("recolhas", recolhas_jsonl(), ERC_RECOLHAS_INDEX),
    ):
        docs = list(_iter_jsonl(path))
        if chave != "recolhas":
            progresso["phase"] = f"a indexar {chave}"
        if not docs:
            saida[chave] = {"index": index, "indexed": 0, "docs": 0}
            continue
        if chave == "recolhas":
            # As recolhas não têm `doc_id` próprio: usa-se o `recolha_id`.
            docs = [{**doc, "doc_id": doc.get("doc_id") or doc.get("recolha_id") or uuid.uuid4().hex} for doc in docs]
        resultado = index_erc_bulk(index, docs, recriar=forcar)
        resultado["docs"] = len(docs)
        saida[chave] = resultado
        if resultado.get("error"):
            erros.append(f"{chave}: {resultado['error']}")
    progresso["phase"] = "concluído"
    saida["errors"] = erros
    return saida


# ---------------------------------------------------------------------------
# Leitura: meta, fichas, pesquisa e painel
# ---------------------------------------------------------------------------

def _ler_jsonl(path: Path) -> List[Dict[str, Any]]:
    return list(_iter_jsonl(path))


def meta() -> Dict[str, Any]:
    """Estado do módulo: pastas, volumetria em disco e índices usados."""
    from api.elasticsearch_client import (
        ERC_ENTIDADES_INDEX,
        ERC_OCS_INDEX,
        ERC_PESSOAS_INDEX,
        ERC_RECOLHAS_INDEX,
    )

    entidades = _ler_jsonl(entidades_jsonl())
    pessoas = _ler_jsonl(pessoas_jsonl())
    ocs = _ler_jsonl(ocs_jsonl())
    recolhas = _ler_jsonl(recolhas_jsonl())
    listagem: Dict[str, Any] = {}
    if listagem_json().exists():
        try:
            listagem = json.loads(listagem_json().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            listagem = {}
    orgaos = set()
    distritos = set()
    anos_financeiro: set = set()
    com_financeiro = 0
    bandas: Dict[str, int] = {}
    for entidade in entidades:
        if entidade.get("distrito"):
            distritos.add(entidade["distrito"])
        if int(entidade.get("n_anos_financeiro") or 0) > 0:
            com_financeiro += 1
        for item in entidade.get("financeiro") or []:
            if item.get("ano"):
                anos_financeiro.add(int(item["ano"]))
        banda = str(((entidade.get("analise") or {}).get("risco") or {}).get("banda") or "sem dados")
        bandas[banda] = bandas.get(banda, 0) + 1
        for pessoa in entidade.get("pessoas") or []:
            if pessoa.get("tipo_orgao"):
                orgaos.add(pessoa["tipo_orgao"])
    por_tipo: Dict[str, int] = {}
    for recolha in recolhas:
        chave = str(recolha.get("tipo") or "outro")
        por_tipo[chave] = por_tipo.get(chave, 0) + 1
    return {
        "fonte": FONTE,
        "portal": erc.BASE_URL,
        "data_dir": str(data_dir()),
        "indices": {
            "entidades": ERC_ENTIDADES_INDEX,
            "pessoas": ERC_PESSOAS_INDEX,
            "ocs": ERC_OCS_INDEX,
            "recolhas": ERC_RECOLHAS_INDEX,
        },
        "contagens": {
            "entidades": len(entidades),
            "pessoas": len(pessoas),
            "ocs": len(ocs),
            "recolhas": len(recolhas),
            "distritos": len(distritos),
            "tipos_orgao": sorted(orgaos),
            "entidades_com_financeiro": com_financeiro,
            "anos_financeiro": sorted(anos_financeiro, reverse=True),
            "recolhas_por_tipo": dict(sorted(por_tipo.items(), key=lambda kv: -kv[1])),
            "bandas_risco": dict(sorted(bandas.items(), key=lambda kv: -kv[1])),
        },
        "listagem": {
            "cached_at": listagem.get("cached_at"),
            "total_portal": listagem.get("total"),
        },
        "ficheiros": {
            "entidades": str(entidades_jsonl().name),
            "pessoas": str(pessoas_jsonl().name),
            "ocs": str(ocs_jsonl().name),
            "recolhas": str(recolhas_jsonl().name),
        },
    }


def get_entidade(entidade_id: str) -> Optional[Dict[str, Any]]:
    """Ficha de uma entidade a partir do JSONL (funciona sem Elasticsearch)."""
    alvo = str(entidade_id).lower()
    for doc in _iter_jsonl(entidades_jsonl()):
        if str(doc.get("doc_id") or "").lower() == alvo:
            return doc
    return None


def get_pessoa(pessoa_id: str) -> Optional[Dict[str, Any]]:
    """Ficha de uma pessoa a partir do JSONL (funciona sem Elasticsearch)."""
    alvo = str(pessoa_id).lower()
    for doc in _iter_jsonl(pessoas_jsonl()):
        if str(doc.get("doc_id") or "").lower() == alvo:
            return doc
    return None


def _filtrar_docs(
    docs: Iterable[Dict[str, Any]],
    *,
    q: Optional[str] = None,
    campos_texto: Tuple[str, ...] = (),
    distrito: Optional[str] = None,
    exactos: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Filtragem local (fallback sem Elasticsearch) sobre os documentos em disco."""
    termo = (q or "").strip().lower()
    distrito_l = (distrito or "").strip().lower()
    exactos = exactos or {}
    out: List[Dict[str, Any]] = []
    for doc in docs:
        if distrito_l and distrito_l not in str(doc.get("distrito") or "").lower():
            continue
        if any(str(doc.get(campo) or "").lower() != valor.lower() for campo, valor in exactos.items()):
            continue
        if termo:
            haystack = " | ".join(str(doc.get(campo) or "") for campo in campos_texto).lower()
            if termo not in haystack:
                continue
        out.append(doc)
    return out


def listar_entidades(
    *,
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    tipo_sociedade: Optional[str] = None,
    page: int = 1,
    size: int = 25,
    usar_es: bool = True,
) -> Dict[str, Any]:
    """Lista/pesquisa entidades (Elasticsearch quando disponível, JSONL em recurso)."""
    if usar_es:
        from api.elasticsearch_client import search_erc_entidades

        resultado = search_erc_entidades(q=q, distrito=distrito, tipo_sociedade=tipo_sociedade, size=size, page=page)
        if not resultado.get("error"):
            resultado["origem"] = "elasticsearch"
            return resultado
    docs = _filtrar_docs(
        _iter_jsonl(entidades_jsonl()),
        q=q,
        campos_texto=("nome", "ocs_designacoes", "pessoas_nomes"),
        distrito=distrito,
        exactos={"tipo_sociedade": tipo_sociedade} if tipo_sociedade else None,
    )
    docs.sort(key=lambda d: str(d.get("nome") or ""))
    inicio = max(0, (page - 1) * size)
    return {"total": len(docs), "items": docs[inicio: inicio + size], "page": page, "size": size, "origem": "jsonl"}


def listar_pessoas(
    *,
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    empresa: Optional[str] = None,
    funcao: Optional[str] = None,
    page: int = 1,
    size: int = 25,
    usar_es: bool = True,
) -> Dict[str, Any]:
    """Lista/pesquisa pessoas reguladas."""
    if usar_es:
        from api.elasticsearch_client import search_erc_pessoas

        resultado = search_erc_pessoas(q=q, distrito=distrito, empresa=empresa, funcao=funcao, size=size, page=page)
        if not resultado.get("error"):
            resultado["origem"] = "elasticsearch"
            return resultado
    docs = _filtrar_docs(
        _iter_jsonl(pessoas_jsonl()),
        q=q,
        campos_texto=("nome", "empresas", "participacoes_nomes"),
        distrito=distrito,
    )
    if empresa:
        alvo = empresa.strip().lower()
        docs = [d for d in docs if any(alvo in str(e).lower() for e in (d.get("empresas") or []))]
    if funcao:
        alvo = funcao.strip().lower()
        docs = [d for d in docs if any(alvo in str(o.get("funcao") or "").lower() for o in (d.get("orgaos") or []))]
    docs.sort(key=lambda d: str(d.get("nome") or ""))
    inicio = max(0, (page - 1) * size)
    return {"total": len(docs), "items": docs[inicio: inicio + size], "page": page, "size": size, "origem": "jsonl"}


def listar_ocs(
    *,
    q: Optional[str] = None,
    tipo: Optional[str] = None,
    distrito: Optional[str] = None,
    proprietaria: Optional[str] = None,
    page: int = 1,
    size: int = 25,
    usar_es: bool = True,
) -> Dict[str, Any]:
    """Lista/pesquisa órgãos de comunicação social."""
    if usar_es:
        from api.elasticsearch_client import search_erc_ocs

        resultado = search_erc_ocs(q=q, tipo=tipo, distrito=distrito, proprietaria=proprietaria, size=size, page=page)
        if not resultado.get("error"):
            resultado["origem"] = "elasticsearch"
            return resultado
    docs = _filtrar_docs(
        _iter_jsonl(ocs_jsonl()),
        q=q,
        campos_texto=("designacao", "entidade_proprietaria"),
        distrito=distrito,
        exactos={"tipo": tipo} if tipo else None,
    )
    if proprietaria:
        alvo = proprietaria.strip().lower()
        docs = [d for d in docs if alvo in str(d.get("entidade_proprietaria") or "").lower()]
    docs.sort(key=lambda d: str(d.get("designacao") or ""))
    inicio = max(0, (page - 1) * size)
    return {"total": len(docs), "items": docs[inicio: inicio + size], "page": page, "size": size, "origem": "jsonl"}


def listar_analise(
    *,
    q: Optional[str] = None,
    banda: Optional[str] = None,
    nivel_transparencia: Optional[str] = None,
    nivel_credito: Optional[str] = None,
    distrito: Optional[str] = None,
    risco_min: Optional[float] = None,
    risco_max: Optional[float] = None,
    transparencia_min: Optional[float] = None,
    credito_min: Optional[float] = None,
    com_financeiro: Optional[bool] = None,
    ordenar: str = "risco",
    page: int = 1,
    size: int = 25,
    usar_es: bool = True,
) -> Dict[str, Any]:
    """Ranking de análise de risco (Elasticsearch quando disponível, JSONL em recurso)."""
    if usar_es:
        from api.elasticsearch_client import search_erc_analise

        resultado = search_erc_analise(
            q=q, banda=banda, nivel_transparencia=nivel_transparencia, nivel_credito=nivel_credito, distrito=distrito,
            risco_min=risco_min, risco_max=risco_max, transparencia_min=transparencia_min, credito_min=credito_min,
            com_financeiro=com_financeiro, ordenar=ordenar, size=size, page=page,
        )
        if not resultado.get("error"):
            resultado["origem"] = "elasticsearch"
            return resultado
    docs = _analise_no_disco(
        _iter_jsonl(entidades_jsonl()),
        q=q, banda=banda, nivel_transparencia=nivel_transparencia, nivel_credito=nivel_credito, distrito=distrito,
        risco_min=risco_min, risco_max=risco_max, transparencia_min=transparencia_min, credito_min=credito_min,
        com_financeiro=com_financeiro, ordenar=ordenar,
    )
    inicio = max(0, (page - 1) * size)
    return {"total": len(docs), "items": docs[inicio: inicio + size], "page": page, "size": size, "origem": "jsonl"}


def _ordem_doc(doc: Dict[str, Any], ordenar: str) -> Any:
    """Chave de ordenação local (o ES faz o mesmo com os campos homónimos)."""
    analise = doc.get("analise") or {}
    campos = {
        "risco": (analise.get("risco") or {}).get("score"),
        "transparencia": (analise.get("transparencia") or {}).get("score"),
        "credito": (analise.get("credito") or {}).get("score"),
        "rendimentos": doc.get("ultimo_rendimentos"),
        "resultados": doc.get("ultimo_resultados"),
        "capital_proprio": doc.get("ultimo_capital_proprio"),
        "autonomia": doc.get("ultimo_autonomia"),
        "recentes": doc.get("ultimo_ano_financeiro"),
    }
    valor = campos.get(str(ordenar or "risco").lower())
    if valor is None:
        return (1, 0.0, str(doc.get("nome") or ""))
    return (0, -float(valor), str(doc.get("nome") or "")) if ordenar != "nome" else (0, float(valor), str(doc.get("nome") or ""))


def _analise_no_disco(
    docs: Iterable[Dict[str, Any]],
    *,
    q: Optional[str] = None,
    banda: Optional[str] = None,
    nivel_transparencia: Optional[str] = None,
    nivel_credito: Optional[str] = None,
    distrito: Optional[str] = None,
    risco_min: Optional[float] = None,
    risco_max: Optional[float] = None,
    transparencia_min: Optional[float] = None,
    credito_min: Optional[float] = None,
    com_financeiro: Optional[bool] = None,
    ordenar: str = "risco",
) -> List[Dict[str, Any]]:
    """Filtragem e ordenação da análise sem Elasticsearch."""
    def _um_de(valor: Optional[str], alvo: Any) -> bool:
        if valor is None:
            return True
        return str(alvo or "") in [parte.strip() for parte in str(valor).split(",") if parte.strip()]

    termo = (q or "").strip().lower()
    distrito_l = (distrito or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for doc in docs:
        analise = doc.get("analise") or {}
        risco = (analise.get("risco") or {}).get("score")
        transparencia = (analise.get("transparencia") or {}).get("score") or 0
        credito = (analise.get("credito") or {}).get("score")
        anos = int(doc.get("n_anos_financeiro") or 0)
        if not _um_de(banda, (analise.get("risco") or {}).get("banda")):
            continue
        if not _um_de(nivel_transparencia, (analise.get("transparencia") or {}).get("nivel")):
            continue
        if not _um_de(nivel_credito, (analise.get("credito") or {}).get("nivel")):
            continue
        if distrito_l and distrito_l not in str(doc.get("distrito") or "").lower():
            continue
        if risco_min is not None and (risco is None or risco < risco_min):
            continue
        if risco_max is not None and (risco is None or risco > risco_max):
            continue
        if transparencia_min is not None and transparencia < transparencia_min:
            continue
        if credito_min is not None and (credito is None or credito < credito_min):
            continue
        if com_financeiro is True and not anos:
            continue
        if com_financeiro is False and anos:
            continue
        if termo:
            haystack = " | ".join(str(doc.get(campo) or "") for campo in ("nome", "tipo_sociedade", "actividade_principal", "distrito")).lower()
            if termo not in haystack:
                continue
        out.append(doc)
    if str(ordenar or "risco").lower() == "nome":
        out.sort(key=lambda d: str(d.get("nome") or ""))
    else:
        out.sort(key=lambda d: _ordem_doc(d, ordenar))
    return out


def painel_financeiro() -> Dict[str, Any]:
    """Painel financeiro do módulo (agregações no ES; JSONL quando não há ES)."""
    from api.elasticsearch_client import erc_financeiro_painel

    painel = erc_financeiro_painel()
    if not painel.get("error"):
        painel["origem"] = "elasticsearch"
        return painel

    entidades = _ler_jsonl(entidades_jsonl())
    por_ano: Dict[int, Dict[str, float]] = {}
    bandas: Dict[str, int] = {}
    transparencias: Dict[str, int] = {}
    creditos: Dict[str, int] = {}
    com_financeiro = 0
    for doc in entidades:
        analise = doc.get("analise") or {}
        banda = str((analise.get("risco") or {}).get("banda") or "sem dados")
        bandas[banda] = bandas.get(banda, 0) + 1
        nivel = str((analise.get("transparencia") or {}).get("nivel") or "sem dados")
        transparencias[nivel] = transparencias.get(nivel, 0) + 1
        nivel_c = str((analise.get("credito") or {}).get("nivel") or "sem dados")
        creditos[nivel_c] = creditos.get(nivel_c, 0) + 1
        for item in doc.get("financeiro") or []:
            ano = int(item.get("ano") or 0)
            if not ano:
                continue
            com_financeiro += 0 if ano in por_ano else 0
            balde = por_ano.setdefault(ano, {"balancos": 0, "rendimentos": 0.0, "resultados": 0.0, "ativo": 0.0, "capital_proprio": 0.0, "com_prejuizo": 0})
            balde["balancos"] += 1
            for campo, chave in (("rendimentos_totais", "rendimentos"), ("resultados_liquidos", "resultados"), ("ativo_total", "ativo"), ("capital_proprio", "capital_proprio")):
                valor = item.get(campo)
                if isinstance(valor, (int, float)):
                    balde[chave] += float(valor)
            if isinstance(item.get("resultados_liquidos"), (int, float)) and item["resultados_liquidos"] < 0:
                balde["com_prejuizo"] += 1
    com_financeiro = sum(1 for doc in entidades if int(doc.get("n_anos_financeiro") or 0))
    anos = [
        {"ano": ano, **{**balde, "rendimentos": round(balde["rendimentos"], 2), "resultados": round(balde["resultados"], 2),
                        "ativo": round(balde["ativo"], 2), "capital_proprio": round(balde["capital_proprio"], 2)}}
        for ano, balde in sorted(por_ano.items(), reverse=True)
    ]
    return {
        "com_financeiro": com_financeiro,
        "por_banda": [{"key": k, "count": v} for k, v in sorted(bandas.items(), key=lambda kv: -kv[1])],
        "por_transparencia": [{"key": k, "count": v} for k, v in sorted(transparencias.items(), key=lambda kv: -kv[1])],
        "por_credito": [{"key": k, "count": v} for k, v in sorted(creditos.items(), key=lambda kv: -kv[1])],
        "anos": anos,
        "origem": "jsonl",
    }


def resumo() -> Dict[str, Any]:
    """Painel do módulo: contagens, distritos, tipos de sociedade e top detentores."""
    entidades = _ler_jsonl(entidades_jsonl())
    pessoas = _ler_jsonl(pessoas_jsonl())
    ocs = _ler_jsonl(ocs_jsonl())

    distritos: Dict[str, int] = {}
    tipos: Dict[str, int] = {}
    actividades: Dict[str, int] = {}
    funcoes: Dict[str, int] = {}
    tipos_ocs: Dict[str, int] = {}
    sem_ocs = 0
    com_financeiro = 0
    bandas: Dict[str, int] = {}
    transparencias: Dict[str, int] = {}
    creditos: Dict[str, int] = {}
    anos_financeiro: Dict[int, int] = {}
    empresas_com_pessoas = 0
    for entidade in entidades:
        if entidade.get("distrito"):
            distritos[entidade["distrito"]] = distritos.get(entidade["distrito"], 0) + 1
        if entidade.get("tipo_sociedade"):
            tipos[entidade["tipo_sociedade"]] = tipos.get(entidade["tipo_sociedade"], 0) + 1
        if entidade.get("actividade_principal"):
            actividades[entidade["actividade_principal"]] = actividades.get(entidade["actividade_principal"], 0) + 1
        if entidade.get("detem_ocs") is False:
            sem_ocs += 1
        if int(entidade.get("n_pessoas") or 0) > 0:
            empresas_com_pessoas += 1
        if int(entidade.get("n_anos_financeiro") or 0) > 0:
            com_financeiro += 1
        for ano_item in entidade.get("financeiro") or []:
            ano_chave = int(ano_item.get("ano") or 0)
            if ano_chave:
                anos_financeiro[ano_chave] = anos_financeiro.get(ano_chave, 0) + 1
        analise = entidade.get("analise") or {}
        banda = str((analise.get("risco") or {}).get("banda") or "sem dados")
        bandas[banda] = bandas.get(banda, 0) + 1
        nivel_t = str((analise.get("transparencia") or {}).get("nivel") or "sem dados")
        transparencias[nivel_t] = transparencias.get(nivel_t, 0) + 1
        nivel_c = str((analise.get("credito") or {}).get("nivel") or "sem dados")
        creditos[nivel_c] = creditos.get(nivel_c, 0) + 1
        for pessoa in entidade.get("pessoas") or []:
            if pessoa.get("funcao"):
                funcoes[pessoa["funcao"]] = funcoes.get(pessoa["funcao"], 0) + 1
    for item in ocs:
        if item.get("tipo"):
            tipos_ocs[item["tipo"]] = tipos_ocs.get(item["tipo"], 0) + 1

    def _top(contagens: Dict[str, int], limite: int = 20) -> List[Dict[str, Any]]:
        return [{"key": key, "count": count} for key, count in sorted(contagens.items(), key=lambda kv: -kv[1])[:limite]]

    pessoas_com_empresa = sum(1 for p in pessoas if int(p.get("n_empresas") or 0) > 0)
    pessoas_com_participacao = sum(1 for p in pessoas if int(p.get("n_participacoes") or 0) > 0)
    return {
        "entidades": len(entidades),
        "pessoas": len(pessoas),
        "ocs": len(ocs),
        "entidades_sem_ocs": sem_ocs,
        "entidades_com_pessoas": empresas_com_pessoas,
        "entidades_com_financeiro": com_financeiro,
        "anos_financeiro": [{"key": str(ano), "count": count} for ano, count in sorted(anos_financeiro.items(), reverse=True)],
        "bandas_risco": _top(bandas, 10),
        "niveis_transparencia": _top(transparencias, 10),
        "niveis_credito": _top(creditos, 10),
        "pessoas_com_cargos": pessoas_com_empresa,
        "pessoas_com_participacoes": pessoas_com_participacao,
        "distritos": _top(distritos),
        "tipos_sociedade": _top(tipos),
        "actividades": _top(actividades, 10),
        "funcoes": _top(funcoes, 25),
        "tipos_ocs": _top(tipos_ocs),
    }


def export_csv(tipo: str = "entidades", *, maximo: int = 50000) -> str:
    """Exporta entidades, pessoas, OCS, análise de risco ou série financeira."""
    tipo = (tipo or "entidades").lower()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if tipo == "pessoas":
        writer.writerow(["id", "nome", "distrito", "actividade_principal", "n_empresas", "empresas", "n_participacoes", "participacoes"])
        for doc in _ler_jsonl(pessoas_jsonl())[:maximo]:
            writer.writerow([
                doc.get("doc_id"), doc.get("nome"), doc.get("distrito"), doc.get("actividade_principal"),
                doc.get("n_empresas"), "; ".join(doc.get("empresas") or []),
                doc.get("n_participacoes"), "; ".join(doc.get("participacoes_nomes") or []),
            ])
    elif tipo == "ocs":
        writer.writerow(["id", "designacao", "tipo", "entidade_proprietaria", "distrito"])
        for doc in _ler_jsonl(ocs_jsonl())[:maximo]:
            writer.writerow([doc.get("doc_id"), doc.get("designacao"), doc.get("tipo"), doc.get("entidade_proprietaria"), doc.get("distrito")])
    elif tipo == "financeiro":
        writer.writerow([
            "id", "nome", "distrito", "ano", "ativo_total", "passivo_total", "capital_proprio", "rendimentos_totais",
            "resultados_liquidos", "responsabilidades_nao_inscritas", "autonomia_financeira", "endividamento",
            "crescimento_rendimentos", "confidencialidade",
        ])
        for doc in _ler_jsonl(entidades_jsonl())[:maximo]:
            for item in doc.get("financeiro") or []:
                writer.writerow([
                    doc.get("doc_id"), doc.get("nome"), doc.get("distrito"), item.get("ano"), item.get("ativo_total"),
                    item.get("passivo_total") or item.get("passivos_totais"), item.get("capital_proprio"),
                    item.get("rendimentos_totais"), item.get("resultados_liquidos"), item.get("responsabilidades_nao_inscritas"),
                    item.get("autonomia_financeira"), item.get("endividamento"), item.get("crescimento_rendimentos"),
                    item.get("confidencialidade"),
                ])
    elif tipo == "analise":
        writer.writerow([
            "id", "nome", "distrito", "transparencia", "nivel_transparencia", "credito", "nivel_credito",
            "risco", "banda_risco", "n_anos_financeiro", "ultimo_ano", "alertas",
        ])
        for doc in _ler_jsonl(entidades_jsonl())[:maximo]:
            analise = doc.get("analise") or {}
            writer.writerow([
                doc.get("doc_id"), doc.get("nome"), doc.get("distrito"),
                (analise.get("transparencia") or {}).get("score"), (analise.get("transparencia") or {}).get("nivel"),
                (analise.get("credito") or {}).get("score"), (analise.get("credito") or {}).get("nivel"),
                (analise.get("risco") or {}).get("score"), (analise.get("risco") or {}).get("banda"),
                doc.get("n_anos_financeiro"), doc.get("ultimo_ano_financeiro"),
                "; ".join(analise.get("alertas") or []),
            ])
    else:
        writer.writerow([
            "id", "nome", "tipo_sociedade", "actividade_principal", "distrito", "detem_ocs", "capital_social",
            "n_ocs", "n_pessoas", "ocs", "pessoas", "transparencia", "nivel_transparencia", "credito",
            "nivel_credito", "risco", "banda_risco", "n_anos_financeiro", "ultimo_ano_financeiro",
            "ultimo_rendimentos", "ultimo_resultados", "ultimo_autonomia",
        ])
        for doc in _ler_jsonl(entidades_jsonl())[:maximo]:
            analise = doc.get("analise") or {}
            writer.writerow([
                doc.get("doc_id"), doc.get("nome"), doc.get("tipo_sociedade"), doc.get("actividade_principal"),
                doc.get("distrito"), doc.get("detem_ocs"), doc.get("capital_social"),
                doc.get("n_ocs"), doc.get("n_pessoas"),
                "; ".join(doc.get("ocs_designacoes") or []), "; ".join(doc.get("pessoas_nomes") or []),
                (analise.get("transparencia") or {}).get("score"), (analise.get("transparencia") or {}).get("nivel"),
                (analise.get("credito") or {}).get("score"), (analise.get("credito") or {}).get("nivel"),
                (analise.get("risco") or {}).get("score"), (analise.get("risco") or {}).get("banda"),
                doc.get("n_anos_financeiro"), doc.get("ultimo_ano_financeiro"),
                doc.get("ultimo_rendimentos"), doc.get("ultimo_resultados"), doc.get("ultimo_autonomia"),
            ])
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Trabalhos em segundo plano
# ---------------------------------------------------------------------------

def _prune_jobs() -> None:
    if len(_JOBS) <= _JOBS_KEEP:
        return
    for job_id in sorted(_JOBS, key=lambda jid: str(_JOBS[jid].get("started_at") or ""))[: len(_JOBS) - _JOBS_KEEP]:
        _JOBS.pop(job_id, None)


def start_job(tipo: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Arranca um trabalho (`recolher` ou `indexar`) em segundo plano."""
    tipo = (tipo or "").lower()
    if tipo not in TIPOS_JOB:
        raise ValueError(f"Tipo de trabalho desconhecido: {tipo}")
    with _JOBS_LOCK:
        for job in _JOBS.values():
            if job.get("status") == _RUNNING and job.get("tipo") == tipo:
                return {"job_id": job["job_id"], "tipo": tipo, "status": _RUNNING,
                        "already_running": True, "message": "Já existe um trabalho deste tipo a correr."}
        job: Dict[str, Any] = {
            "job_id": uuid.uuid4().hex[:12],
            "tipo": tipo,
            "status": _RUNNING,
            "started_at": _now(),
            "finished_at": None,
            "payload": dict(payload or {}),
            "progress": {
                "phase": "a começar",
                "entidades_total": 0,
                "entidades_done": 0,
                "pessoas_total": 0,
                "pessoas_done": 0,
                "registos": 0,
                "current": None,
            },
            "result": None,
            "error": None,
        }
        _JOBS[job["job_id"]] = job
        _prune_jobs()
    threading.Thread(target=_run_job, args=(job,), name=f"erc-{tipo}", daemon=True).start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    try:
        payload = job["payload"]
        progresso = job["progress"]
        if job["tipo"] == "recolher":
            resultado = recolher(
                limite=payload.get("limite"),
                pausa=float(payload.get("pausa") or PAUSA_PADRAO),
                com_pessoas=bool(payload.get("com_pessoas", True)),
                com_estrutura=bool(payload.get("com_estrutura", True)),
                com_ocs=bool(payload.get("com_ocs", True)),
                com_financeiro=bool(payload.get("com_financeiro", False)),
                guardar_html=bool(payload.get("guardar_html", True)),
                forcar=bool(payload.get("forcar")),
                saltar_existentes=bool(payload.get("saltar_existentes")),
                trabalhadores=int(payload.get("trabalhadores") or 1),
                progresso=progresso,
            )
            if payload.get("indexar"):
                progresso["phase"] = "a indexar"
                resultado["indexacao"] = indexar(progresso=progresso)
        elif job["tipo"] == "recolher_financeiro":
            resultado = recolher_financeiro(
                limite=payload.get("limite"),
                ano_inicio=payload.get("ano_inicio"),
                ano_fim=payload.get("ano_fim"),
                vazios_seguidos=int(payload.get("vazios_seguidos") or 0),
                pausa=float(payload.get("pausa") or PAUSA_PADRAO),
                trabalhadores=int(payload.get("trabalhadores") or 8),
                apenas_sem_financeiro=bool(payload.get("apenas_sem_financeiro", True)),
                guardar_html=bool(payload.get("guardar_html", False)),
                progresso=progresso,
            )
            if payload.get("indexar"):
                progresso["phase"] = "a indexar"
                resultado["indexacao"] = indexar(progresso=progresso)
        elif job["tipo"] == "analisar":
            resultado = recalcular_analises(progresso=progresso)
            if payload.get("indexar"):
                progresso["phase"] = "a indexar"
                resultado["indexacao"] = indexar(progresso=progresso)
        else:
            resultado = indexar(progresso=progresso)
        job["result"] = resultado
        job["status"] = "error" if resultado.get("error") else "done"
        job["finished_at"] = _now()
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Trabalho da ERC falhou")
        job["status"] = "error"
        job["finished_at"] = _now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["progress"]["phase"] = "erro"
    finally:
        job["progress"]["current"] = None


def list_jobs() -> Dict[str, Any]:
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""), reverse=True)
        return {"total": len(jobs), "items": [dict(job) for job in jobs]}


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id))
        return dict(job) if job else None
