"""Importação dos **Contratos Públicos do Portal Base** (IMPIC) de dados.gov.pt.

O conjunto «Contratos Públicos - Portal Base - IMPIC» publica, por ano, um **ZIP**
(com um único `Contratos<ano>.json`) e um XLSX equivalente. O endereço do ZIP
muda a cada actualização semanal, por isso o URL nunca é escrito à mão: é sempre
lido da API do dados.gov.pt.

Este módulo faz o que a página de administração promete:

1. `listar_recursos()` — os ficheiros por ano (zip/xlsx, tamanho, data de
   actualização), direto da API do dados.gov.pt;
2. `inspecionar(ano)` — o **formato real** do ZIP: que ficheiro traz dentro, se é
   um *array* JSON ou NDJSON, quais os campos de cada contrato e um exemplo;
3. `importar(ano)` — descarrega, normaliza (com o `normalize_contract` já usado
   pelo pipeline de contratos) e indexa no índice `contratos` em lotes de 1000,
   com progresso e cancelamento. É **idempotente** por `idcontrato`, por isso
   repetir a importação actualiza em vez de duplicar.

O ficheiro grande é lido em *streaming*: o JSON do ano tem centenas de MB e
carregá-lo para memória (como o import por upload faz, para ficheiros pequenos)
não é aceitável.
"""
from __future__ import annotations

import io
import json
import logging
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import httpx

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

#: Conjunto de dados no dados.gov.pt (CKAN). O `slug` muda quando o IMPIC alarga
#: o intervalo de anos (2025 → 2026): se o dataset mudar de nome, é aqui.
DATASET_SLUG = "contratos-publicos-portal-base-impic-contratos-de-2012-a-2026"
DATASET_API = f"https://dados.gov.pt/api/1/datasets/{DATASET_SLUG}/"

#: Onde ficam os ZIP descarregados (a mesma pasta que o pipeline de contratos usa).
CACHE_DIR = ROOT / "data" / "contratos-gov-portal-base"

#: Tamanho do lote enviado ao Elasticsearch e do buffer de leitura do JSON.
LOTE_INDEXACAO = 1000
BLOCO_LEITURA = 1 << 20  # 1 MB

_TTL_RECURSOS = 600  # segundos: a API não precisa de ser chamada a cada clique
_cache: Dict[str, Any] = {"em": 0.0, "recursos": None}

#: Estado das importações (uma por ano). Vive no processo: a página mostra-o e a
#: importação é retomável por ser idempotente por `idcontrato`.
_trabalhos: Dict[int, Dict[str, Any]] = {}
_trava = threading.Lock()


# ---------------------------------------------------------------------------
# Recursos do dados.gov.pt
# ---------------------------------------------------------------------------
def listar_recursos(*, forcar: bool = False) -> List[Dict[str, Any]]:
    """Ficheiros do conjunto (um ZIP e um XLSX por ano), da API do dados.gov.pt."""
    agora = time.time()
    if not forcar and _cache["recursos"] and agora - float(_cache["em"]) < _TTL_RECURSOS:
        return _cache["recursos"]

    with httpx.Client(timeout=120, follow_redirects=True) as cliente:
        resposta = cliente.get(DATASET_API)
        resposta.raise_for_status()
        dados = resposta.json()

    recursos: List[Dict[str, Any]] = []
    for recurso in dados.get("resources") or []:
        titulo = str(recurso.get("title") or "")
        ano = "".join(ch for ch in titulo if ch.isdigit())[:4]
        recursos.append(
            {
                "titulo": titulo,
                "ano": ano,
                "formato": (recurso.get("format") or "").lower(),
                "bytes": int(recurso.get("filesize") or 0),
                "atualizado_em": str(recurso.get("last_modified") or "")[:19],
                "url": str(recurso.get("url") or ""),
                "url_estavel": str(recurso.get("latest") or ""),
                "sha1": str((recurso.get("checksum") or {}).get("value") or ""),
                "id": str(recurso.get("id") or ""),
            }
        )
    recursos.sort(key=lambda item: (item["ano"], item["formato"]))
    _cache.update({"em": agora, "recursos": recursos})
    return recursos


def anos_disponiveis(recursos: Optional[List[Dict[str, Any]]] = None) -> List[int]:
    itens = recursos if recursos is not None else listar_recursos()
    return sorted({int(item["ano"]) for item in itens if item["ano"].isdigit()})


def ano_atual() -> int:
    """Ano mais recente com ZIP no conjunto (não o ano do relógio: em Janeiro o
    conjunto ainda pode não ter o ano novo)."""
    recursos = listar_recursos()
    anos = [int(item["ano"]) for item in recursos if item["formato"] == "zip" and item["ano"].isdigit()]
    if anos:
        return max(anos)
    return datetime.now(timezone.utc).year


def encontrar_recurso(
    recursos: List[Dict[str, Any]], ano: int | str, formato: str = "zip"
) -> Optional[Dict[str, Any]]:
    alvo_ano, alvo_formato = str(ano), formato.lower()
    return next(
        (item for item in recursos if item["ano"] == alvo_ano and item["formato"] == alvo_formato),
        None,
    )


def caminho_local(ano: int | str, formato: str = "zip") -> Path:
    return CACHE_DIR / f"contratos{ano}.{formato}"


# ---------------------------------------------------------------------------
# Descarregamento
# ---------------------------------------------------------------------------
def _sha1(ficheiro: Path, *, limite: Optional[int] = None) -> str:
    import hashlib

    digest = hashlib.sha1()
    with ficheiro.open("rb") as fluxo:
        while True:
            pedaco = fluxo.read(1 << 20)
            if not pedaco:
                break
            digest.update(pedaco)
    return digest.hexdigest()


def descarregar(
    recurso: Dict[str, Any],
    *,
    progresso: Optional[Callable[[int, int], None]] = None,
    forcar: bool = False,
) -> Path:
    """Descarrega o recurso para a pasta de cache.

    Reutiliza o ficheiro local **só se for o mesmo** que está publicado: o conjunto
    é actualizado semanalmente e o ZIP em cache podia ter um mês — importar isso
    daria contratos em falta sem ninguém dar por isso. A verificação é pelo
    `sha1` publicado (ou, sem ele, pelo tamanho).
    """
    destino = caminho_local(recurso["ano"], recurso["formato"])
    esperado = int(recurso.get("bytes") or 0)
    sha1_publicado = str(recurso.get("sha1") or "")
    if destino.exists() and not forcar:
        tamanho_ok = not esperado or destino.stat().st_size == esperado
        if tamanho_ok and (not sha1_publicado or _sha1(destino) == sha1_publicado):
            if progresso:
                progresso(destino.stat().st_size, destino.stat().st_size)
            return destino
        logger.info(
            "Portal Base: %s em cache está desactualizado (%s) — a descarregar de novo.",
            destino.name,
            "sha1 diferente" if tamanho_ok else "tamanho diferente",
        )

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".parcial")
    lidos = 0
    with httpx.Client(timeout=None, follow_redirects=True) as cliente:
        with cliente.stream("GET", recurso["url"]) as resposta:
            resposta.raise_for_status()
            total = int(resposta.headers.get("content-length") or esperado or 0)
            with temporario.open("wb") as saida:
                for pedaco in resposta.iter_bytes(BLOCO_LEITURA):
                    saida.write(pedaco)
                    lidos += len(pedaco)
                    if progresso:
                        progresso(lidos, total)
    temporario.replace(destino)
    logger.info("Portal Base: %s descarregado (%s bytes)", destino.name, lidos)
    return destino


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------
def membro_json(origem: Any) -> Optional[zipfile.ZipInfo]:
    """Primeiro `.json` dentro do ZIP (aceita um `Path` ou um `ZipFile` já aberto)."""
    if isinstance(origem, zipfile.ZipFile):
        return next((m for m in origem.infolist() if m.filename.lower().endswith(".json")), None)
    with zipfile.ZipFile(origem) as zipper:
        return next((m for m in zipper.infolist() if m.filename.lower().endswith(".json")), None)


def _forma_json(texto: str) -> str:
    limpo = texto.lstrip()
    if limpo.startswith("["):
        return "array JSON"
    if limpo.startswith("{"):
        return "objeto JSON (possivelmente NDJSON)"
    return "desconhecida"


def _primeiro_registo(texto: str) -> Optional[Dict[str, Any]]:
    inicio = texto.find("{")
    if inicio < 0:
        return None
    codificador = json.JSONDecoder()
    try:
        valor, _ = codificador.raw_decode(texto[inicio:])
    except ValueError:
        fim = texto.rfind("}")
        if fim <= inicio:
            return None
        try:
            valor, _ = codificador.raw_decode(texto[inicio : fim + 1])
        except ValueError:
            return None
    return valor if isinstance(valor, dict) else None


def inspecionar(ano: int | str, *, descarregar_se_preciso: bool = True) -> Dict[str, Any]:
    """Descreve o formato do ZIP de um ano (membro, forma, campos e exemplo)."""
    recursos = listar_recursos()
    recurso = encontrar_recurso(recursos, ano, "zip")
    if not recurso:
        return {"erro": f"Não há ZIP para o ano {ano} em dados.gov.pt.", "ano": str(ano)}

    caminho = caminho_local(ano, "zip")
    if not caminho.exists():
        if not descarregar_se_preciso:
            return {
                "ano": str(ano),
                "recurso": recurso,
                "descarregado": False,
                "nota": "O ZIP ainda não está em cache; o formato é lido ao descarregar.",
            }
        caminho = descarregar(recurso)

    with zipfile.ZipFile(caminho) as zipper:
        membros = [
            {"nome": m.filename, "bytes": m.file_size, "comprimido": m.compress_size} for m in zipper.infolist()
        ]
        membro = membro_json(caminho)
        if not membro:
            return {"ano": str(ano), "recurso": recurso, "membros": membros, "erro": "O ZIP não traz nenhum JSON."}
        with zipper.open(membro) as fluxo:
            inicio = fluxo.read(32 * 1024)

    texto = inicio.decode("utf-8", errors="replace")
    registo = _primeiro_registo(texto) or {}
    campos = [
        {"nome": chave, "tipo": type(valor).__name__, "exemplo": str(valor)[:120]}
        for chave, valor in registo.items()
    ]
    return {
        "ano": str(ano),
        "recurso": recurso,
        "descarregado": True,
        "ficheiro_local": str(caminho),
        "membros": membros,
        "membro_json": membro.filename,
        "membro_bytes": membro.file_size,
        "forma": _forma_json(texto),
        "total_campos": len(campos),
        "campos": campos,
        "exemplo_inicio": texto[:200].replace("\n", " "),
        "indice_destino": "contratos",
        "normalizacao": "collectors.contratos.normalize_contract",
    }


# ---------------------------------------------------------------------------
# Leitura em streaming
# ---------------------------------------------------------------------------
def iter_registos(zip_path: Path, *, bloco: int = BLOCO_LEITURA, limite: Optional[int] = None) -> Iterator[Dict[str, Any]]:
    """Itera os contratos do JSON dentro do ZIP, sem carregar o ficheiro para memória.

    Usa `JSONDecoder.raw_decode` sobre um buffer: funciona tanto para um *array*
    como para NDJSON, e não depende do `ijson` estar instalado.
    """
    with zipfile.ZipFile(zip_path) as zipper:
        membro = membro_json(zipper)
        if not membro:
            raise ValueError(f"O ZIP {zip_path.name} não traz nenhum JSON.")
        with zipper.open(membro) as fluxo:
            codificador = json.JSONDecoder()
            buffer = ""
            entregues = 0
            while True:
                pedaco = fluxo.read(bloco).decode("utf-8", errors="replace")
                buffer += pedaco
                indice = 0
                while True:
                    inicio = buffer.find("{", indice)
                    if inicio < 0:
                        buffer = buffer[indice:]
                        break
                    try:
                        valor, fim = codificador.raw_decode(buffer, inicio)
                    except ValueError:
                        # Registo cortado a meio: espera pelo resto do bloco.
                        buffer = buffer[inicio:]
                        break
                    indice = fim
                    if isinstance(valor, dict):
                        yield valor
                        entregues += 1
                        if limite and entregues >= limite:
                            return
                if not pedaco:
                    return


def _normalizador():
    """`normalize_contract` do pipeline de contratos (import tardio: o módulo vive em `collectors`)."""
    import sys

    raiz = str(ROOT)
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from collectors.contratos import normalize_contract  # type: ignore

    return normalize_contract


# ---------------------------------------------------------------------------
# Importação
# ---------------------------------------------------------------------------
def _estado_base(ano: int) -> Dict[str, Any]:
    return {
        "ano": ano,
        "estado": "parado",
        "fase": "",
        "mensagem": "",
        "bytes_lidos": 0,
        "bytes_total": 0,
        "registos": 0,
        "indexados": 0,
        "erros": 0,
        "lotes": 0,
        "cancelar": False,
        "iniciado_em": None,
        "terminado_em": None,
    }


def estado(ano: Optional[int] = None) -> Any:
    with _trava:
        if ano is not None:
            return dict(_trabalhos.get(int(ano)) or _estado_base(int(ano)))
        return {str(chave): dict(valor) for chave, valor in _trabalhos.items()}


def cancelar(ano: int) -> Dict[str, Any]:
    with _trava:
        trabalho = _trabalhos.get(int(ano))
        if not trabalho or trabalho["estado"] != "a_correr":
            return {"ano": int(ano), "cancelado": False, "mensagem": "Não há importação a correr para este ano."}
        trabalho["cancelar"] = True
    return {"ano": int(ano), "cancelado": True, "mensagem": "Pedido de paragem enviado."}


def importar(
    ano: int | str,
    *,
    limite: Optional[int] = None,
    descarregar_se_preciso: bool = True,
    utilizador: str = "",
) -> Dict[str, Any]:
    """Arranca a importação de um ano em segundo plano (idempotente por `idcontrato`)."""
    ano_int = int(ano)
    with _trava:
        atual = _trabalhos.get(ano_int)
        if atual and atual["estado"] == "a_correr":
            return {"iniciado": False, "mensagem": f"Já há uma importação de {ano_int} a correr.", **dict(atual)}
        _trabalhos[ano_int] = _estado_base(ano_int)

    thread = threading.Thread(
        target=_correr_importacao,
        args=(ano_int, limite, descarregar_se_preciso, utilizador),
        name=f"base-impic-{ano_int}",
        daemon=True,
    )
    thread.start()
    return {"iniciado": True, "ano": ano_int, "mensagem": f"Importação de {ano_int} iniciada em segundo plano."}


def _atualizar(ano: int, **campos: Any) -> None:
    with _trava:
        trabalho = _trabalhos.get(ano)
        if trabalho:
            trabalho.update(campos)


def _correr_importacao(ano: int, limite: Optional[int], descarregar_se_preciso: bool, utilizador: str) -> None:
    from api.elasticsearch_client import get_es_client, index_contracts

    _atualizar(ano, estado="a_correr", fase="a preparar", iniciado_em=_agora(), utilizador=utilizador)
    try:
        recursos = listar_recursos()
        recurso = encontrar_recurso(recursos, ano, "zip")
        if not recurso:
            _atualizar(ano, estado="erro", mensagem=f"Não há ZIP para {ano} em dados.gov.pt.", terminado_em=_agora())
            return

        def progresso(lidos: int, total: int) -> None:
            _atualizar(ano, fase="a descarregar", bytes_lidos=lidos, bytes_total=total)

        if descarregar_se_preciso:
            caminho = descarregar(recurso, progresso=progresso)
        else:
            caminho = caminho_local(ano, "zip")
            if not caminho.exists():
                _atualizar(ano, estado="erro", mensagem="O ZIP não está em cache.", terminado_em=_agora())
                return

        normalizar = _normalizador()
        cliente = get_es_client()
        if not cliente:
            _atualizar(ano, estado="erro", mensagem="Elasticsearch indisponível.", terminado_em=_agora())
            return

        _atualizar(
            ano,
            fase="a indexar",
            bytes_lidos=caminho.stat().st_size,
            bytes_total=caminho.stat().st_size,
            registos=0,
            indexados=0,
            erros=0,
            lotes=0,
        )
        lote: List[Dict[str, Any]] = []
        for bruto in iter_registos(caminho, limite=limite):
            if _cancelado(ano):
                _atualizar(ano, estado="cancelado", mensagem="Importação cancelada pelo utilizador.", terminado_em=_agora())
                return
            try:
                lote.append(normalizar(bruto))
            except Exception:  # noqa: BLE001 - um registo mau não trava o ano
                _atualizar(ano, erros=int(estado(ano)["erros"]) + 1)
                continue
            if len(lote) >= LOTE_INDEXACAO:
                _indexar_lote(ano, lote, index_contracts)
                lote = []
        if lote:
            _indexar_lote(ano, lote, index_contracts)

        atual = estado(ano)
        _atualizar(
            ano,
            estado="concluido",
            fase="terminado",
            mensagem=(
                f"{atual['indexados']} contratos indexados de {atual['registos']} lidos"
                + (f" ({atual['erros']} com erro)" if atual["erros"] else "")
            ),
            terminado_em=_agora(),
        )
    except Exception as exc:  # noqa: BLE001 - o estado mostra o erro à interface
        logger.exception("Importação do Portal Base (%s) falhou", ano)
        _atualizar(ano, estado="erro", mensagem=f"{type(exc).__name__}: {exc}", terminado_em=_agora())


def _indexar_lote(ano: int, lote: List[Dict[str, Any]], indexar: Callable[..., Dict[str, Any]]) -> None:
    resultado = indexar(list(lote))
    atual = estado(ano)
    _atualizar(
        ano,
        registos=int(atual["registos"]) + len(lote),
        indexados=int(atual["indexados"]) + int(resultado.get("indexed_count") or 0),
        erros=int(atual["erros"]) + int(resultado.get("errors") or 0) + (len(lote) if resultado.get("error") else 0),
        lotes=int(atual["lotes"]) + 1,
        mensagem=resultado.get("error") or "",
    )


def _cancelado(ano: int) -> bool:
    with _trava:
        trabalho = _trabalhos.get(ano)
        return bool(trabalho and trabalho.get("cancelar"))


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Estado do índice
# ---------------------------------------------------------------------------
def resumo_indice() -> Dict[str, Any]:
    """Quantos contratos existem no índice, por ano (e o total)."""
    from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

    cliente = get_es_client()
    if not cliente:
        return {"disponivel": False, "erro": "Elasticsearch indisponível"}
    try:
        resposta = cliente.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {"anos": {"terms": {"field": "Ano", "size": 30, "order": {"_key": "desc"}}}},
            },
        )
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc)}
    baldes = ((resposta.get("aggregations") or {}).get("anos") or {}).get("buckets") or []
    total = ((resposta.get("hits") or {}).get("total") or {}).get("value") or 0
    return {
        "disponivel": True,
        "indice": CONTRACTS_INDEX,
        "total": int(total),
        "por_ano": [{"ano": balde.get("key"), "contratos": balde.get("doc_count")} for balde in baldes],
    }


def cache_local() -> List[Dict[str, Any]]:
    """ZIP já descarregados nesta instalação (com tamanho e data)."""
    if not CACHE_DIR.exists():
        return []
    itens = []
    for ficheiro in sorted(CACHE_DIR.glob("contratos*.zip")):
        ano = "".join(ch for ch in ficheiro.stem if ch.isdigit())
        itens.append(
            {
                "ano": ano,
                "ficheiro": ficheiro.name,
                "bytes": ficheiro.stat().st_size,
                "modificado_em": datetime.fromtimestamp(ficheiro.stat().st_mtime, timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    return itens


def amostra(ano: int | str, *, registos: int = 3) -> Dict[str, Any]:
    """Primeiros registos do ZIP (para a página mostrar o que vai ser importado)."""
    caminho = caminho_local(ano, "zip")
    if not caminho.exists():
        return {"erro": "O ZIP ainda não está em cache.", "ano": str(ano)}
    normalizar = _normalizador()
    itens = []
    for bruto in iter_registos(caminho, limite=max(1, registos)):
        try:
            doc = normalizar(bruto)
        except Exception:  # noqa: BLE001
            continue
        itens.append(
            {
                "idcontrato": doc.get("idcontrato"),
                "Ano": doc.get("Ano"),
                "objectoContrato": str(doc.get("objectoContrato") or "")[:160],
                "precoContratual": doc.get("precoContratual"),
                "adjudicantes": [e.get("nome") for e in (doc.get("adjudicantes") or {}).get("parsed") or []][:2],
                "adjudicatarios": [e.get("nome") for e in (doc.get("adjudicatarios") or {}).get("parsed") or []][:2],
                "cpv": [c.get("code") for c in doc.get("cpv") or []][:2],
            }
        )
    return {"ano": str(ano), "itens": itens}
