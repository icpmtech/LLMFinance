"""Serviço do módulo **Entidade para a Transparência** (declarações únicas).

A plataforma da EPT publica, por titular de cargo político ou alto cargo
público, as **declarações únicas** (facto determinante, dados pessoais,
rendimentos, ativo, passivo e registo de interesses). O coletor
(`collectors/entidade_transparencia.py`) lê a API pública; este serviço:

1. **recolhe** o catálogo (entidades → cargos → titulares) e as declarações de
   cada titular, com pausa entre pedidos e retoma incremental;
2. guarda tudo em `data/entidade-transparencia` (JSONL + manifesto);
3. **indexa** em `finance_ept_titulares`, `finance_ept_titularidades`,
   `finance_ept_declaracoes` e `finance_ept_recolhas`;
4. serve a pesquisa, a ficha do titular, a declaração e a ligação ao
   **PessoasIQ** (a «ficha do político»).

A ligação ao PessoasIQ é feita por **nome** (a EPT não publica o NIF do
titular): normaliza-se o nome e procura-se em `finance_people`, aceitando
apenas semelhança alta para não trocar homónimos.
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

from api import elasticsearch_client as esc
from collectors import entidade_transparencia as ept

logger = logging.getLogger(__name__)

DATA_DIR_ENV = "ENTIDADE_TRANSPARENCIA_DATA_DIR"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "entidade-transparencia"
_MANIFEST = "_manifest.json"
_NORMALIZED_DIRNAME = "_normalized"

_CACHE_TTL = 6 * 3600  # catálogo: 6 horas
_MEM_CACHE: Dict[str, tuple[float, Any]] = {}
_MEM_LOCK = threading.Lock()

_JOBS_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_KEEP = 20
_RUNNING = "running"
TIPOS_JOB = ("recolher", "indexar", "exportar", "validar")

_LOTE_ES = 500

NATUREZAS = ept.NATUREZAS
ESTADOS = ept.ESTADOS


# ---------------------------------------------------------------------------
# Pastas, cache e manifesto
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _substituir(temporario: Path, destino: Path, *, tentativas: int = 7) -> None:
    """Troca atómica de ficheiros, com recuo para o Windows.

    No Windows o `os.replace` falha com `PermissionError` quando outro processo
    (a API a servir leituras) tem o destino aberto; insiste-se um pouco.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            temporario.replace(destino)
            return
        except PermissionError:
            if tentativa == tentativas:
                raise
            time.sleep(0.2 * tentativa)


def data_dir() -> Path:
    """Pasta do módulo (configurável por `ENTIDADE_TRANSPARENCIA_DATA_DIR`)."""
    return Path(os.getenv(DATA_DIR_ENV) or _DEFAULT_DATA_DIR)


def catalogo_dir() -> Path:
    return data_dir() / "catalogo"


def normalized_dir() -> Path:
    return data_dir() / _NORMALIZED_DIRNAME


def entidades_json_dir() -> Path:
    """Pasta dos `.json` por entidade (uma entrada por entidade da EPT)."""
    return data_dir() / "entidades"


def _manifest_path() -> Path:
    return data_dir() / _MANIFEST


def read_manifest() -> Dict[str, Any]:
    caminho = _manifest_path()
    if not caminho.exists():
        return {"titulares": {}, "totais": {}}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - um manifesto corrompido não trava o módulo
        logger.warning("Manifesto da Entidade para a Transparência ilegível; a recomeçar")
        return {"titulares": {}, "totais": {}}
    dados.setdefault("titulares", {})
    dados.setdefault("totais", {})
    return dados


def _write_manifest(manifest: Dict[str, Any]) -> None:
    caminho = _manifest_path()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    manifest["atualizado_em"] = _now()
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _substituir(temporario, caminho)


def _contar_linhas(caminho: Path) -> int:
    """Registos de um JSONL (uma entrada por linha, sem `json.loads`)."""
    if not caminho.exists():
        return 0
    total = 0
    with caminho.open("r", encoding="utf-8") as ficheiro:
        for _ in ficheiro:
            total += 1
    return total


def _append_jsonl(caminho: Path, linhas: Iterable[Dict[str, Any]]) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with caminho.open("a", encoding="utf-8") as ficheiro:
        for linha in linhas:
            ficheiro.write(json.dumps(linha, ensure_ascii=False) + "\n")
            total += 1
    return total


def _iter_jsonl(caminho: Path) -> Iterator[Dict[str, Any]]:
    if not caminho.exists():
        return
    with caminho.open("r", encoding="utf-8") as ficheiro:
        for linha in ficheiro:
            linha = linha.strip()
            if not linha:
                continue
            try:
                yield json.loads(linha)
            except Exception:  # noqa: BLE001 - uma linha má não trava a leitura
                continue


def _iter_unicos(caminho: Path, campo: str) -> Iterator[Dict[str, Any]]:
    """Percorre o JSONL sem repetições (a última linha de cada `campo` vence).

    As recolhas incrementais acrescentam linhas; o titular e a declaração mais
    recentes são os que valem, tal como na indexação por `_id`.
    """
    ultimos: Dict[str, Dict[str, Any]] = {}
    for item in _iter_jsonl(caminho):
        chave = item.get(campo)
        if chave:
            ultimos[str(chave)] = item
    yield from ultimos.values()


def _declaracoes_jsonl() -> Path:
    return normalized_dir() / "declaracoes.jsonl"


def _titulares_jsonl() -> Path:
    return normalized_dir() / "titulares.jsonl"


def _titularidades_jsonl() -> Path:
    return catalogo_dir() / "titularidades.jsonl"


# ---------------------------------------------------------------------------
# Catálogo (entidades → cargos → titulares)
# ---------------------------------------------------------------------------


def _cache_path(nome: str) -> Path:
    return catalogo_dir() / f"{nome}.json"


def _mem_get(chave: str) -> Optional[Any]:
    with _MEM_LOCK:
        entrada = _MEM_CACHE.get(chave)
    if not entrada:
        return None
    timestamp, valor = entrada
    if time.time() - timestamp > _CACHE_TTL:
        return None
    return valor


def _mem_set(chave: str, valor: Any) -> None:
    with _MEM_LOCK:
        _MEM_CACHE[chave] = (time.time(), valor)


def _ler_cache(nome: str, *, max_idade: float = _CACHE_TTL) -> Optional[List[Dict[str, Any]]]:
    caminho = _cache_path(nome)
    if not caminho.exists():
        return None
    if time.time() - caminho.stat().st_mtime > max_idade:
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return dados if isinstance(dados, list) else None


def _guardar_cache(nome: str, itens: List[Dict[str, Any]]) -> None:
    caminho = _cache_path(nome)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")
    _substituir(temporario, caminho)


def _catalogo(
    nome: str,
    *,
    forcar: bool = False,
    carregar,
    cliente: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Lê o catálogo da memória, do disco ou da API (por esta ordem)."""
    chave = f"catalogo:{nome}"
    if not forcar:
        em_memoria = _mem_get(chave)
        if em_memoria is not None:
            return em_memoria
        em_disco = _ler_cache(nome)
        if em_disco is not None:
            _mem_set(chave, em_disco)
            return em_disco
    cliente = cliente or ept.make_client()
    itens = carregar(cliente)
    _guardar_cache(nome, itens)
    _mem_set(chave, itens)
    return itens


def entidades(*, forcar: bool = False) -> List[Dict[str, Any]]:
    """Entidades/órgãos com titularidades declaradas."""
    return _catalogo("entidades", forcar=forcar, carregar=ept.fetch_entities)


def cargos(
    *,
    entidade_id: Optional[str] = None,
    titular_id: Optional[str] = None,
    orgao_id: Optional[str] = None,
    forcar: bool = False,
) -> List[Dict[str, Any]]:
    """Cargos da cascata; sem filtros devolve o catálogo completo (em cache)."""
    if not any((entidade_id, titular_id, orgao_id)):
        return _catalogo("cargos", forcar=forcar, carregar=ept.fetch_roles)
    chave = f"cargos:{entidade_id}:{titular_id}:{orgao_id}"
    if not forcar:
        em_memoria = _mem_get(chave)
        if em_memoria is not None:
            return em_memoria
    cliente = ept.make_client()
    itens = ept.fetch_roles(
        cliente,
        entity_id=entidade_id,
        holder_id=titular_id,
        board_id=orgao_id,
    )
    _mem_set(chave, itens)
    return itens


def orgaos(
    *,
    entidade_id: Optional[str] = None,
    cargo_id: Optional[str] = None,
    titular_id: Optional[str] = None,
    forcar: bool = False,
) -> List[Dict[str, Any]]:
    """Órgãos da cascata."""
    if not any((entidade_id, cargo_id, titular_id)):
        return _catalogo("orgaos", forcar=forcar, carregar=ept.fetch_boards)
    chave = f"orgaos:{entidade_id}:{cargo_id}:{titular_id}"
    if not forcar:
        em_memoria = _mem_get(chave)
        if em_memoria is not None:
            return em_memoria
    cliente = ept.make_client()
    itens = ept.fetch_boards(
        cliente,
        entity_id=entidade_id,
        role_id=cargo_id,
        holder_id=titular_id,
    )
    _mem_set(chave, itens)
    return itens


def titulares(
    *,
    entidade_id: Optional[str] = None,
    cargo_id: Optional[str] = None,
    orgao_id: Optional[str] = None,
    q: Optional[str] = None,
    forcar: bool = False,
    limite: int = 500,
) -> List[Dict[str, Any]]:
    """Titulares: cascata entidade → cargo → nome, ou o catálogo completo."""
    if any((entidade_id, cargo_id, orgao_id)):
        chave = f"titulares:{entidade_id}:{cargo_id}:{orgao_id}"
        itens = _mem_get(chave) if not forcar else None
        if itens is None:
            cliente = ept.make_client()
            itens = ept.fetch_holders(
                cliente,
                entity_id=entidade_id,
                role_id=cargo_id,
                board_id=orgao_id,
            )
            _mem_set(chave, itens)
    else:
        itens = _catalogo("titulares", forcar=forcar, carregar=ept.fetch_holders)
    if q:
        alvo = ept.normalize_name(q)
        itens = [item for item in itens if alvo in ept.normalize_name(item.get("nome"))]
    return itens[: max(1, int(limite))]


def _titular_do_catalogo(titular_id: str) -> Optional[Dict[str, Any]]:
    chave = str(titular_id)
    for item in titulares(limite=1_000_000):
        if str(item.get("id")) == chave:
            return item
    return None


# ---------------------------------------------------------------------------
# Recolha
# ---------------------------------------------------------------------------


def _posicoes_por_titular(*, forcar: bool = False, pausa: float = ept.PAUSA) -> Dict[str, List[Dict[str, Any]]]:
    """Todas as titularidades (entidade × cargo × titular) agrupadas por titular."""
    caminho = _titularidades_jsonl()
    if caminho.exists() and not forcar and time.time() - caminho.stat().st_mtime < _CACHE_TTL:
        agrupado: Dict[str, List[Dict[str, Any]]] = {}
        for posicao in _iter_jsonl(caminho):
            agrupado.setdefault(str(posicao.get("titular_id")), []).append(posicao)
        return agrupado
    cliente = ept.make_client()
    agrupado = {}
    linhas: List[Dict[str, Any]] = []
    for posicao in ept.iter_positions(cliente, pausa=pausa):
        agrupado.setdefault(str(posicao.get("titular_id")), []).append(posicao)
        linhas.append(posicao)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    with temporario.open("w", encoding="utf-8") as ficheiro:
        for linha in linhas:
            ficheiro.write(json.dumps(linha, ensure_ascii=False) + "\n")
    _substituir(temporario, caminho)
    return agrupado


def ids_declaracoes_conhecidas() -> set[str]:
    """Ids já normalizados em disco (para a recolha ser incremental)."""
    return {str(item.get("declaracao_id")) for item in _iter_jsonl(_declaracoes_jsonl()) if item.get("declaracao_id")}


def recolher(
    *,
    entidade_id: Optional[str] = None,
    cargo_id: Optional[str] = None,
    orgao_id: Optional[str] = None,
    titular_id: Optional[str] = None,
    limite_titulares: Optional[int] = None,
    limite_declaracoes: Optional[int] = None,
    pausa: float = ept.PAUSA,
    forcar: bool = False,
    indexar_no_fim: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
    ao_progresso: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Recolhe catálogo e declarações, guardando JSONL e o manifesto.

    A ordem é a da própria plataforma: **entidade → cargo → titular** e, por
    cada titular, as suas declarações. Com filtros, a cascata é resolvida no
    servidor da EPT (`getallholders`); sem filtros, percorre-se o catálogo.
    """
    progresso = progresso if progresso is not None else {}
    resultado: Dict[str, Any] = {
        "entidades": 0,
        "titulares": 0,
        "declaracoes": 0,
        "declaracoes_novas": 0,
        "titulares_ignorados": 0,
        "errors": [],
        "iniciado_em": _now(),
    }
    progresso.update(
        {
            "phase": "a ler o catálogo",
            "entidades_total": 0,
            "entidades_done": 0,
            "titulares_total": 0,
            "titulares_done": 0,
            "declaracoes": 0,
            "current": None,
        }
    )

    cliente = ept.make_client()
    manifest = read_manifest()

    # 1. Catálogo.
    catalogo_entidades = entidades(forcar=forcar)
    _guardar_cache("entidades", catalogo_entidades)
    resultado["entidades"] = len(catalogo_entidades)
    progresso["entidades_total"] = len(catalogo_entidades)
    progresso["entidades_done"] = len(catalogo_entidades)
    try:
        cargos(forcar=forcar)
        orgaos(forcar=forcar)
    except Exception as exc:  # noqa: BLE001 - os catálogos auxiliares não são críticos
        logger.warning("EPT: catálogo de cargos/órgãos indisponível (%s)", exc)
        resultado["errors"].append({"fonte": "catalogo", "error": f"{type(exc).__name__}: {exc}"})

    alvo_titulares: List[Dict[str, Any]]
    if titular_id:
        encontrado = _titular_do_catalogo(titular_id)
        alvo_titulares = [encontrado] if encontrado else [{"id": str(titular_id), "nome": ""}]
    else:
        alvo_titulares = ept.fetch_holders(
            cliente,
            entity_id=entidade_id,
            role_id=cargo_id,
            board_id=orgao_id,
        )
        if not any((entidade_id, cargo_id, orgao_id)):
            _guardar_cache("titulares", alvo_titulares)

    if limite_titulares:
        alvo_titulares = alvo_titulares[: int(limite_titulares)]
    progresso["titulares_total"] = len(alvo_titulares)

    # 2. Titularidades (datas de exercício), uma leitura por catálogo.
    try:
        posicoes = _posicoes_por_titular(forcar=False, pausa=pausa)
    except Exception as exc:  # noqa: BLE001 - sem datas, as declarações bastam
        logger.warning("EPT: titularidades indisponíveis (%s)", exc)
        posicoes = {}
        resultado["errors"].append({"fonte": "titularidades", "error": f"{type(exc).__name__}: {exc}"})

    conhecidas = ids_declaracoes_conhecidas()
    tocados: set[str] = set()
    entidades_para_exportar: Optional[set[str]] = {str(entidade_id)} if entidade_id else (set() if titular_id else None)

    # 3. Declarações por titular.
    for indice, titular in enumerate(alvo_titulares, start=1):
        tid = str(titular.get("id") or "")
        nome = str(titular.get("nome") or "")
        if not tid:
            continue
        anterior = (manifest.get("titulares") or {}).get(tid) or {}
        if anterior and not forcar and limite_declaracoes is None:
            resultado["titulares_ignorados"] += 1
            progresso["titulares_done"] = indice
            continue
        progresso["current"] = f"{nome or tid} ({tid})"
        try:
            declaracoes_meta = ept.fetch_declarations(cliente, tid)
            if pausa:
                time.sleep(pausa)
        except Exception as exc:  # noqa: BLE001 - um titular mau não trava os restantes
            logger.warning("EPT: falha a ler as declarações de %s (%s)", tid, exc)
            resultado["errors"].append({"titular_id": tid, "nome": nome, "error": f"{type(exc).__name__}: {exc}"})
            progresso["titulares_done"] = indice
            continue

        declaracoes_novas: List[Dict[str, Any]] = []
        if limite_declaracoes:
            declaracoes_meta = declaracoes_meta[: int(limite_declaracoes)]
        for meta in declaracoes_meta:
            did = str(meta.get("declaracao_id") or "")
            if not did:
                continue
            resultado["declaracoes"] += 1
            if did in conhecidas and not forcar:
                continue
            try:
                detalhe = ept.fetch_declaration(cliente, did)
                documento = ept.normalize_declaration({**detalhe, "id": int(did)}, recolhido_em=_now())
                documento.pop("raw", None)  # o payload original volta a ser lido da API a pedido
                _append_jsonl(_declaracoes_jsonl(), [documento])
                conhecidas.add(did)
                declaracoes_novas.append(documento)
                resultado["declaracoes_novas"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("EPT: falha a ler a declaração %s (%s)", did, exc)
                resultado["errors"].append({"declaracao_id": did, "error": f"{type(exc).__name__}: {exc}"})
            if pausa:
                time.sleep(pausa)
            progresso["declaracoes"] = resultado["declaracoes_novas"]

        # Documento do titular: metadados das declarações + posições conhecidas.
        documento_titular = ept.titular_document(
            tid,
            nome,
            declaracoes_meta,
            posicoes=posicoes.get(tid) or [],
            recolhido_em=_now(),
        )
        documento_titular["declaracoes_novas"] = len(declaracoes_novas)
        _append_jsonl(_titulares_jsonl(), [documento_titular])
        tocados.add(tid)
        if entidades_para_exportar is not None:
            for posicao in posicoes.get(tid) or []:
                if posicao.get("entidade_id"):
                    entidades_para_exportar.add(str(posicao["entidade_id"]))
            for declaracao in declaracoes_novas:
                if declaracao.get("entidade_id"):
                    entidades_para_exportar.add(str(declaracao["entidade_id"]))
        manifest.setdefault("titulares", {})[tid] = {
            "nome": nome,
            "declaracoes": len(declaracoes_meta),
            "declaracoes_novas": len(declaracoes_novas),
            "recolhido_em": documento_titular["recolhido_em"],
        }
        manifest["totais"] = {
            "titulares": len(manifest.get("titulares") or {}),
            "declaracoes": len(conhecidas),
        }
        _write_manifest(manifest)
        resultado["titulares"] += 1
        progresso["titulares_done"] = indice
        progresso["current"] = None
        if ao_progresso and (indice % 10 == 0 or indice == len(alvo_titulares)):
            ao_progresso(progresso)

    manifest.setdefault("catalogo", {})
    manifest["catalogo"].update(
        {
            "entidades": len(catalogo_entidades),
            "cargos": len(_ler_cache("cargos") or []),
            "orgaos": len(_ler_cache("orgaos") or []),
            "titulares": len(_ler_cache("titulares") or []),
            "atualizado_em": _now(),
        }
    )
    _write_manifest(manifest)
    resultado["terminado_em"] = _now()

    try:
        resultado["exportacao"] = exportar_entidades_json(
            entidades_para_exportar,
            progresso=progresso,
        )
    except Exception as exc:  # noqa: BLE001 - a exportação não invalida a recolha
        logger.exception("EPT: falha a exportar os JSON por entidade")
        resultado["errors"].append({"fonte": "exportacao", "error": f"{type(exc).__name__}: {exc}"})

    if indexar_no_fim:
        progresso["phase"] = "a indexar"
        resultado["indexacao"] = indexar(forcar=True, progresso=progresso)
    progresso["phase"] = "concluído"
    return resultado


# ---------------------------------------------------------------------------
# Exportação: um `.json` por entidade
# ---------------------------------------------------------------------------


def exportar_entidades_json(
    entidade_ids: Optional[Iterable[str]] = None,
    *,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grava `data/entidade-transparencia/entidades/<id>.json` por entidade.

    Cada ficheiro junta a entidade, os cargos, os titulares dessa entidade e as
    declarações cuja `entidade_id` coincide — com as secções normalizadas e o
    registo de interesses. É a exportação «por entidade» pedida para consumo
    externo (um JSON por entidade, não um único JSONL).
    """
    alvo = {str(identificador) for identificador in entidade_ids} if entidade_ids else None
    progresso = progresso if progresso is not None else {}
    progresso.update({"phase": "a exportar por entidade", "current": None, "registos": 0})

    catalogo = {str(item.get("id")): item.get("nome") for item in entidades()}

    posicoes_por_entidade: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for posicao in _iter_unicos(_titularidades_jsonl(), "titularidade_id"):
        entidade_id = str(posicao.get("entidade_id") or "")
        if not entidade_id or (alvo and entidade_id not in alvo):
            continue
        posicoes_por_entidade[entidade_id].append(posicao)
    if alvo:
        for entidade_id in alvo:
            posicoes_por_entidade.setdefault(entidade_id, [])

    declaracoes_por_entidade: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for documento in _iter_unicos(_declaracoes_jsonl(), "declaracao_id"):
        entidade_id = str(documento.get("entidade_id") or "")
        if not entidade_id or (alvo and entidade_id not in alvo):
            continue
        titular_id = str(documento.get("titular_id") or "")
        if not titular_id:
            continue
        declaracoes_por_entidade[entidade_id][titular_id].append(documento)

    destino = entidades_json_dir()
    destino.mkdir(parents=True, exist_ok=True)
    indice: List[Dict[str, Any]] = []
    total_titulares = 0
    total_declaracoes = 0

    for entidade_id in sorted(posicoes_por_entidade):
        posicoes = posicoes_por_entidade[entidade_id]
        nome = catalogo.get(entidade_id) or (posicoes[0].get("entidade") if posicoes else "") or ""
        titulares: Dict[str, Dict[str, Any]] = {}

        for posicao in posicoes:
            titular_id = str(posicao.get("titular_id") or "")
            if not titular_id:
                continue
            entrada = titulares.setdefault(
                titular_id,
                {"titular_id": titular_id, "nome": posicao.get("titular"), "cargos": [], "declaracoes": []},
            )
            cargo = posicao.get("cargo")
            if cargo and cargo not in entrada["cargos"]:
                entrada["cargos"].append(cargo)

        for titular_id, documentos in declaracoes_por_entidade.get(entidade_id, {}).items():
            entrada = titulares.setdefault(
                titular_id,
                {"titular_id": titular_id, "nome": documentos[0].get("titular"), "cargos": [], "declaracoes": []},
            )
            entrada["declaracoes"] = sorted(
                documentos,
                key=lambda item: (item.get("ano") or 0, item.get("entrega") or ""),
                reverse=True,
            )

        lista = sorted(
            titulares.values(),
            key=lambda item: ept.normalize_name(item.get("nome") or ""),
        )
        cargos = sorted({cargo for item in lista for cargo in item.get("cargos") or []})
        orgaos = sorted(
            {
                documento.get("orgao")
                for item in lista
                for documento in item.get("declaracoes") or []
                if documento.get("orgao")
            }
        )
        documentos_totais = sum(len(item.get("declaracoes") or []) for item in lista)
        documento = {
            "entidade_id": entidade_id,
            "entidade": nome,
            "gerado_em": _now(),
            "fonte": "entidade-transparencia",
            "fonte_url": ept.BASE_WEB,
            "cargos": cargos,
            "orgaos": orgaos,
            "titulares": lista,
            "totais": {"titulares": len(lista), "declaracoes": documentos_totais},
        }
        caminho = destino / f"{entidade_id}.json"
        caminho.write_text(json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8")
        indice.append(
            {
                "entidade_id": entidade_id,
                "entidade": nome,
                "ficheiro": caminho.name,
                "titulares": len(lista),
                "declaracoes": documentos_totais,
                "cargos": len(cargos),
                "orgaos": len(orgaos),
                "gerado_em": documento["gerado_em"],
            }
        )
        total_titulares += len(lista)
        total_declaracoes += documentos_totais
        progresso["registos"] = len(indice)
        progresso["current"] = nome or entidade_id

    (destino / "_index.json").write_text(
        json.dumps(
            {
                "gerado_em": _now(),
                "fonte": "entidade-transparencia",
                "pasta": str(destino),
                "totais": {
                    "entidades": len(indice),
                    "titulares": total_titulares,
                    "declaracoes": total_declaracoes,
                },
                "entidades": indice,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    progresso["phase"] = "exportado"
    progresso["current"] = None
    return {
        "entidades": len(indice),
        "titulares": total_titulares,
        "declaracoes": total_declaracoes,
        "pasta": str(destino),
        "indice": str(destino / "_index.json"),
    }


# ---------------------------------------------------------------------------
# Validação contra a plataforma
# ---------------------------------------------------------------------------

_AMOSTRA_VALIDACAO = 40
_CAMPOS_DECLARACAO = (
    "natureza",
    "estado",
    "entidade",
    "orgao",
    "cargo",
    "ano",
    "inicio",
    "fim",
    "entrega",
)


def _validacao_path() -> Path:
    return data_dir() / "_validacao.json"


def _ler_cache_bruta(nome: str) -> Optional[List[Dict[str, Any]]]:
    """Cache do catálogo sem prazo de validade (o que ficou em disco)."""
    return _ler_cache(nome, max_idade=float("inf"))


def _comparar_catalogo(
    vivos: Iterable[Dict[str, Any]],
    guardados: Iterable[Dict[str, Any]],
    *,
    chave_id: str = "id",
    chave_nome: str = "nome",
) -> Dict[str, Any]:
    indices_vivos = {str(item.get(chave_id)): item for item in vivos or [] if item.get(chave_id)}
    indices_guardados = {str(item.get(chave_id)): item for item in guardados or [] if item.get(chave_id)}
    em_falta = sorted(set(indices_vivos) - set(indices_guardados))
    a_mais = sorted(set(indices_guardados) - set(indices_vivos))
    nomes: List[Dict[str, Any]] = []
    for chave in sorted(set(indices_vivos) & set(indices_guardados)):
        vivo = indices_vivos[chave].get(chave_nome) or ""
        guardado = indices_guardados[chave].get(chave_nome) or ""
        if ept.normalize_name(vivo) != ept.normalize_name(guardado):
            nomes.append({"id": chave, "guardado": guardado, "ao_vivo": vivo})
    return {
        "ok": not (em_falta or a_mais or nomes),
        "ao_vivo": len(indices_vivos),
        "guardados": len(indices_guardados),
        "em_falta": len(em_falta),
        "a_mais": len(a_mais),
        "nomes_divergentes": len(nomes),
        "amostra": {
            "em_falta": [indices_vivos[chave] for chave in em_falta[:_AMOSTRA_VALIDACAO]],
            "a_mais": [indices_guardados[chave] for chave in a_mais[:_AMOSTRA_VALIDACAO]],
            "nomes_divergentes": nomes[:_AMOSTRA_VALIDACAO],
        },
    }


def _cascata(posicoes: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Conjuntos entidade → cargo → titular, em nomes normalizados."""
    entidades: Dict[str, Dict[str, Any]] = {}
    cargos: Dict[tuple, Dict[str, Any]] = {}
    titulares: Dict[tuple, Dict[str, Any]] = {}
    for posicao in posicoes:
        entidade = str(posicao.get("entidade") or "")
        cargo = str(posicao.get("cargo") or "")
        nome = str(posicao.get("titular") or "")
        chave_entidade = ept.normalize_name(entidade)
        chave_cargo = ept.normalize_name(cargo)
        chave_nome = ept.normalize_name(nome)
        if not chave_entidade or not chave_cargo:
            continue
        entidades.setdefault(chave_entidade, {"entidade": entidade})
        cargos.setdefault((chave_entidade, chave_cargo), {"entidade": entidade, "cargo": cargo})
        titulares.setdefault(
            (chave_entidade, chave_cargo, chave_nome),
            {"entidade": entidade, "cargo": cargo, "titular": nome, "titular_id": posicao.get("titular_id")},
        )
    return {"entidades": entidades, "cargos": cargos, "titulares": titulares}


def _comparar_cascata(viva: Dict[str, Any], guardada: Dict[str, Any]) -> Dict[str, Any]:
    resultado: Dict[str, Any] = {}
    for chave, rotulo in (("entidades", "entidade"), ("cargos", "cargo"), ("titulares", "titular")):
        em_falta = sorted(set(viva[chave]) - set(guardada[chave]), key=str)
        a_mais = sorted(set(guardada[chave]) - set(viva[chave]), key=str)
        resultado[chave] = {
            "ok": not (em_falta or a_mais),
            "ao_vivo": len(viva[chave]),
            "guardados": len(guardada[chave]),
            "em_falta": len(em_falta),
            "a_mais": len(a_mais),
            "amostra": {
                "em_falta": [viva[chave][item] for item in em_falta[:_AMOSTRA_VALIDACAO]],
                "a_mais": [guardada[chave][item] for item in a_mais[:_AMOSTRA_VALIDACAO]],
            },
        }
        logger.debug("EPT: validação da cascata (%s) com %d divergências", rotulo, len(em_falta) + len(a_mais))
    return resultado


def _assinatura_declaracao(documento: Dict[str, Any]) -> Dict[str, Any]:
    assinatura = {campo: documento.get(campo) for campo in _CAMPOS_DECLARACAO}
    assinatura["secoes"] = len(documento.get("secoes") or [])
    assinatura["interesses"] = len(documento.get("interesses") or [])
    assinatura["texto"] = len(documento.get("texto") or "")
    return assinatura


def _amostra_uniforme(itens: List[Any], limite: Optional[int]) -> List[Any]:
    """Amostra espalhada pelo catálogo (evita ficar só nos primeiros).

    `None` significa «todos» e `0` significa «nenhum».
    """
    if limite is None:
        return list(itens)
    if limite <= 0 or not itens:
        return []
    if limite >= len(itens):
        return list(itens)
    passo = len(itens) / float(limite)
    return [itens[min(len(itens) - 1, int(posicao * passo))] for posicao in range(int(limite))]


def validar(
    *,
    pausa: float = ept.PAUSA,
    cliente: Any = None,
    limite_titulares: Optional[int] = 0,
    limite_declaracoes: Optional[int] = None,
    progresso: Optional[Dict[str, Any]] = None,
    ao_progresso: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Compara o catálogo e os detalhes guardados com a API pública da EPT.

    A plataforma expõe todas as titularidades (entidade × cargo × titular) numa
    listagem paginada, pelo que a cascata completa — **todas as entidades,
    cargos e nomes de titulares** — é validada sem um pedido por entidade. Os
    detalhes (declarações de cada titular e conteúdo de cada declaração) são
    validados por amostra (`limite_titulares`) ou na totalidade.

    Com `limite_titulares=0` só se valida o catálogo e a cascata; `None`
    valida as declarações de todos os titulares em disco.
    """
    cliente = cliente or ept.make_client()
    progresso = progresso if progresso is not None else {}
    progresso.update({"phase": "a validar", "current": None})

    relatorio: Dict[str, Any] = {
        "gerado_em": _now(),
        "fonte": ept.BASE_API,
        "fonte_url": ept.BASE_WEB,
        "estado": "ok",
        "parametros": {
            "limite_titulares": limite_titulares,
            "limite_declaracoes": limite_declaracoes,
            "pausa": pausa,
        },
        "resumo": {},
        "catalogos": {},
        "cascata": {},
        "detalhes": {"titulares": {}, "declaracoes": {}},
        "errors": [],
    }

    def _registar(fonte: str, exc: Exception) -> None:
        logger.warning("EPT: validação de %s falhou (%s)", fonte, exc)
        relatorio["errors"].append({"fonte": fonte, "error": f"{type(exc).__name__}: {exc}"})

    # 1. Catálogos ao vivo.
    progresso["current"] = "catálogos"
    vivos: Dict[str, List[Dict[str, Any]]] = {}
    for nome, carregar in (
        ("entidades", ept.fetch_entities),
        ("cargos", ept.fetch_roles),
        ("orgaos", ept.fetch_boards),
        ("titulares", ept.fetch_holders),
    ):
        try:
            vivos[nome] = carregar(cliente)
        except Exception as exc:  # noqa: BLE001 - um catálogo falhado não trava o resto
            _registar(nome, exc)
            vivos[nome] = []

    # 2. Titularidades ao vivo: a cascata completa numa só leitura.
    posicoes_vivas: List[Dict[str, Any]] = []
    try:
        for posicao in ept.iter_positions(cliente, pausa=0.0):
            posicoes_vivas.append(posicao)
            if ao_progresso and len(posicoes_vivas) % 2000 == 0:
                progresso["current"] = f"titularidades {len(posicoes_vivas)}"
                ao_progresso(progresso)
    except Exception as exc:  # noqa: BLE001
        _registar("titularidades", exc)

    progresso["current"] = "a comparar catálogos"
    for nome in ("entidades", "cargos", "orgaos", "titulares"):
        if not vivos.get(nome):
            relatorio["catalogos"][nome] = {"ok": None, "nota": "sem resposta da plataforma"}
            continue
        relatorio["catalogos"][nome] = _comparar_catalogo(vivos[nome], _ler_cache_bruta(nome) or [])

    posicoes_guardadas = [
        posicao for posicao in _iter_jsonl(_titularidades_jsonl()) if posicao.get("titularidade_id")
    ]
    if posicoes_vivas and not posicoes_guardadas:
        relatorio["cascata"] = {"ok": None, "nota": "sem titularidades em disco (recolha pendente)"}
    elif posicoes_vivas:
        relatorio["cascata"] = _comparar_cascata(_cascata(posicoes_vivas), _cascata(posicoes_guardadas))
    else:
        relatorio["cascata"] = {"ok": None, "nota": "sem resposta da plataforma"}

    progresso["current"] = "a comparar titularidades"
    indices_vivos = {str(posicao.get("titularidade_id")): posicao for posicao in posicoes_vivas}
    indices_guardados = {str(posicao.get("titularidade_id")): posicao for posicao in posicoes_guardadas}
    em_falta = sorted(set(indices_vivos) - set(indices_guardados))
    a_mais = sorted(set(indices_guardados) - set(indices_vivos))
    datas = [
        {
            "titularidade_id": chave,
            "guardado": {"inicio": indices_guardados[chave].get("inicio"), "fim": indices_guardados[chave].get("fim")},
            "ao_vivo": {"inicio": indices_vivos[chave].get("inicio"), "fim": indices_vivos[chave].get("fim")},
        }
        for chave in sorted(set(indices_vivos) & set(indices_guardados))
        if (indices_vivos[chave].get("inicio"), indices_vivos[chave].get("fim"))
        != (indices_guardados[chave].get("inicio"), indices_guardados[chave].get("fim"))
    ]
    relatorio["titularidades"] = {
        "ok": not (em_falta or a_mais or datas) if (posicoes_vivas or posicoes_guardadas) else None,
        "ao_vivo": len(indices_vivos),
        "guardadas": len(indices_guardados),
        "em_falta": len(em_falta),
        "a_mais": len(a_mais),
        "datas_divergentes": len(datas),
        "amostra": {
            "em_falta": [indices_vivos[chave] for chave in em_falta[:_AMOSTRA_VALIDACAO]],
            "a_mais": [indices_guardados[chave] for chave in a_mais[:_AMOSTRA_VALIDACAO]],
            "datas_divergentes": datas[:_AMOSTRA_VALIDACAO],
        },
    }

    # 3. Detalhes por titular (declarações registadas em cada ficha).
    documentos_titular: Dict[str, Dict[str, Any]] = {}
    for documento in _iter_jsonl(_titulares_jsonl()):
        if documento.get("titular_id"):
            documentos_titular[str(documento["titular_id"])] = documento
    declaracoes_guardadas: Dict[str, Dict[str, Any]] = {}
    por_titular: Dict[str, set] = {}
    for documento in _iter_jsonl(_declaracoes_jsonl()):
        declaracao_id = str(documento.get("declaracao_id") or "")
        if not declaracao_id:
            continue
        declaracoes_guardadas[declaracao_id] = documento
        por_titular.setdefault(str(documento.get("titular_id") or ""), set()).add(declaracao_id)
    alvo = _amostra_uniforme(sorted(documentos_titular), limite_titulares)
    detalhes_titulares: List[Dict[str, Any]] = []
    for indice, titular_id in enumerate(alvo, start=1):
        documento = documentos_titular.get(titular_id) or {}
        progresso["current"] = f"titular {documento.get('nome') or titular_id}"
        progresso["titulares_done"] = indice
        progresso["titulares_total"] = len(alvo)
        try:
            ao_vivo = ept.fetch_declarations(cliente, titular_id)
        except Exception as exc:  # noqa: BLE001
            _registar(f"titular {titular_id}", exc)
            continue
        if pausa:
            time.sleep(pausa)
        ids_vivos = {str(item.get("declaracao_id")) for item in ao_vivo if item.get("declaracao_id")}
        ids_guardados = por_titular.get(titular_id) or set()
        faltam = sorted(ids_vivos - ids_guardados)
        a_mais = sorted(ids_guardados - ids_vivos)
        esperado = documento.get("declaracoes_total")
        if faltam or a_mais or (esperado is not None and int(esperado or 0) != len(ids_vivos)):
            detalhes_titulares.append(
                {
                    "titular_id": titular_id,
                    "nome": documento.get("nome"),
                    "ao_vivo": len(ids_vivos),
                    "guardadas": len(ids_guardados),
                    "declaracoes_total_guardado": esperado,
                    "em_falta": faltam[:_AMOSTRA_VALIDACAO],
                    "a_mais": a_mais[:_AMOSTRA_VALIDACAO],
                }
            )
        if ao_progresso and (indice % 10 == 0 or indice == len(alvo)):
            ao_progresso(progresso)
    relatorio["detalhes"]["titulares"] = {
        "ok": not detalhes_titulares,
        "verificados": len(alvo),
        "divergentes": len(detalhes_titulares),
        "amostra": detalhes_titulares[:_AMOSTRA_VALIDACAO],
    }

    # 4. Detalhes de cada declaração (secções, naturezas, interesses).
    por_id = declaracoes_guardadas
    alvo_declaracoes = _amostra_uniforme(sorted(por_id), limite_declaracoes)
    divergencias_declaracoes: List[Dict[str, Any]] = []
    falhadas: List[Dict[str, Any]] = []
    for indice, declaracao_id in enumerate(alvo_declaracoes, start=1):
        progresso["current"] = f"declaração {declaracao_id}"
        try:
            payload = ept.fetch_declaration(cliente, declaracao_id)
            ao_vivo = ept.normalize_declaration({**payload, "id": int(declaracao_id)})
        except Exception as exc:  # noqa: BLE001
            _registar(f"declaração {declaracao_id}", exc)
            falhadas.append({"declaracao_id": declaracao_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if pausa:
            time.sleep(pausa)
        assinatura_guardada = _assinatura_declaracao(por_id[declaracao_id])
        assinatura_viva = _assinatura_declaracao(ao_vivo)
        diferencas = [
            {"campo": campo, "guardado": assinatura_guardada.get(campo), "ao_vivo": assinatura_viva.get(campo)}
            for campo in assinatura_viva
            if assinatura_guardada.get(campo) != assinatura_viva.get(campo)
        ]
        if diferencas:
            divergencias_declaracoes.append({"declaracao_id": declaracao_id, "campos": diferencas})
        if ao_progresso and (indice % 10 == 0 or indice == len(alvo_declaracoes)):
            ao_progresso(progresso)
    relatorio["detalhes"]["declaracoes"] = {
        "ok": not divergencias_declaracoes,
        "verificadas": len(alvo_declaracoes),
        "divergentes": len(divergencias_declaracoes),
        "ilegiveis": len(falhadas),
        "amostra": divergencias_declaracoes[:_AMOSTRA_VALIDACAO],
    }

    # 5. Resumo.
    seccoes = {
        "entidades": relatorio["catalogos"].get("entidades") or {},
        "cargos": relatorio["catalogos"].get("cargos") or {},
        "orgaos": relatorio["catalogos"].get("orgaos") or {},
        "nomes_de_titulares": relatorio["catalogos"].get("titulares") or {},
        "cascata_entidade_cargo": (relatorio["cascata"] or {}).get("cargos") or {},
        "cascata_cargo_titular": (relatorio["cascata"] or {}).get("titulares") or {},
        "titularidades": relatorio["titularidades"],
        "declaracoes_por_titular": relatorio["detalhes"]["titulares"],
        "declaracoes": relatorio["detalhes"]["declaracoes"],
    }
    divergencias = 0
    for seccao in seccoes.values():
        parcial = sum(
            int(seccao.get(campo) or 0)
            for campo in ("em_falta", "a_mais", "nomes_divergentes", "datas_divergentes", "divergentes")
        )
        seccao["divergencias"] = parcial
        divergencias += parcial
    catalogo_entidades = relatorio["catalogos"].get("entidades") or {}
    catalogo_titulares = relatorio["catalogos"].get("titulares") or {}
    relatorio["resumo"] = {
        "entidades_ao_vivo": len(vivos.get("entidades") or []),
        "cargos_ao_vivo": len(vivos.get("cargos") or []),
        "titulares_ao_vivo": len(vivos.get("titulares") or []),
        "titularidades_ao_vivo": len(posicoes_vivas),
        "entidades_guardadas": int(catalogo_entidades.get("guardados") or 0),
        "titulares_guardados": int(catalogo_titulares.get("guardados") or 0),
        "fichas_de_titular_guardadas": len(documentos_titular),
        "declaracoes_guardadas": len(por_id),
        "divergencias": divergencias,
        "verificacoes": {
            chave: {campo: valor for campo, valor in (seccao or {}).items() if campo != "amostra"}
            for chave, seccao in seccoes.items()
        },
    }
    relatorio["estado"] = "ok" if divergencias == 0 and not relatorio["errors"] else "divergencias"
    relatorio["terminado_em"] = _now()

    caminho = _validacao_path()
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = caminho.with_suffix(".tmp")
        temporario.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
        _substituir(temporario, caminho)
        relatorio["ficheiro"] = str(caminho)
    except Exception as exc:  # noqa: BLE001 - o relatório devolvido continua válido
        _registar("relatorio", exc)

    progresso["phase"] = "concluído"
    progresso["current"] = None
    return relatorio


def ler_validacao() -> Optional[Dict[str, Any]]:
    """Último relatório de validação gravado em disco."""
    caminho = _validacao_path()
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Indexação
# ---------------------------------------------------------------------------


def _cliente(es: Any = None) -> Any:
    return es or esc.get_es_client()


def indexar(
    *,
    forcar: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Indexa o que está em disco nos índices `finance_ept_*`."""
    from elasticsearch.helpers import bulk

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível", "indexados": 0}

    esc.ensure_indices(cliente)
    resultado: Dict[str, Any] = {"indexados": 0, "titulares": 0, "declaracoes": 0, "titularidades": 0, "errors": []}
    progresso = progresso if progresso is not None else {}
    progresso.update({"phase": "a indexar", "current": None})

    lotes = [
        (esc.EPT_TITULARES_INDEX, _titulares_jsonl(), "titular_id", "titulares"),
        (esc.EPT_DECLARACOES_INDEX, _declaracoes_jsonl(), "declaracao_id", "declaracoes"),
        (esc.EPT_TITULARIDADES_INDEX, _titularidades_jsonl(), "titularidade_id", "titularidades"),
    ]
    for indice, caminho, campo_id, chave_resultado in lotes:
        if not caminho.exists():
            continue
        progresso["current"] = caminho.name
        acoes: List[Dict[str, Any]] = []
        enviados = 0
        try:
            for documento in _iter_unicos(caminho, campo_id):
                identificador = documento.get(campo_id)
                if not identificador:
                    continue
                fonte = {chave: valor for chave, valor in documento.items() if chave != "raw"}
                if indice == esc.EPT_DECLARACOES_INDEX:
                    fonte.setdefault("titular_normalizado", ept.normalize_name(fonte.get("titular")))
                fonte["ingested_at"] = _now()
                acoes.append(
                    {
                        "_index": indice,
                        "_id": f"ept:{identificador}" if indice == esc.EPT_DECLARACOES_INDEX else str(identificador),
                        "_source": fonte,
                    }
                )
                if len(acoes) >= _LOTE_ES:
                    enviados += _enviar(cliente, bulk, acoes)
                    acoes = []
            if acoes:
                enviados += _enviar(cliente, bulk, acoes)
        except Exception as exc:  # noqa: BLE001 - um ficheiro mau não trava os restantes
            logger.exception("EPT: falha a indexar %s", caminho)
            resultado["errors"].append({"ficheiro": caminho.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        resultado[chave_resultado] = enviados
        resultado["indexados"] += enviados
        progresso["registos"] = resultado["indexados"]

    # O manifesto vira o histórico das recolhas.
    manifest = read_manifest()
    try:
        cliente.index(
            index=esc.EPT_RECOLHAS_INDEX,
            id="ept",
            document={
                "recolha_id": "ept",
                "fonte": "entidade-transparencia",
                "totais": manifest.get("totais") or {},
                "catalogo": manifest.get("catalogo") or {},
                "atualizado_em": manifest.get("atualizado_em") or _now(),
                "ingested_at": _now(),
            },
        )
        resultado["recolhas"] = 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("EPT: recolha não registada (%s)", exc)

    for indice in (esc.EPT_TITULARES_INDEX, esc.EPT_DECLARACOES_INDEX, esc.EPT_TITULARIDADES_INDEX):
        try:
            cliente.indices.refresh(index=indice)
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh de %s ignorado: %s", indice, exc)
    progresso["phase"] = "indexado"
    progresso["current"] = None
    return resultado


def _enviar(cliente: Any, bulk: Any, acoes: List[Dict[str, Any]]) -> int:
    sucesso, _ = bulk(cliente, acoes, refresh=False, raise_on_error=False)
    return int(sucesso or 0)


# ---------------------------------------------------------------------------
# Pesquisa
# ---------------------------------------------------------------------------


def _sem_texto_da_fonte(fonte: Dict[str, Any]) -> Dict[str, Any]:
    return {chave: valor for chave, valor in fonte.items() if chave not in ("raw", "secoes", "texto")}


def _filtros_declaracoes(
    *,
    titular_id: Optional[str] = None,
    titular: Optional[str] = None,
    entidade: Optional[str] = None,
    cargo: Optional[str] = None,
    orgao: Optional[str] = None,
    ano: Optional[int] = None,
    natureza: Optional[str] = None,
    com_interesses: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    filtros: List[Dict[str, Any]] = []
    if titular_id:
        filtros.append({"term": {"titular_id": str(titular_id)}})
    if titular:
        filtros.append({"match_phrase": {"titular": titular}})
    if entidade:
        filtros.append({"match_phrase": {"entidade": entidade}})
    if cargo:
        filtros.append({"match_phrase": {"cargo": cargo}})
    if orgao:
        filtros.append({"match_phrase": {"orgao": orgao}})
    if ano:
        filtros.append({"term": {"ano": int(ano)}})
    if natureza:
        filtros.append({"term": {"natureza": natureza}})
    if com_interesses is not None:
        filtros.append({"term": {"tem_registo_interesses": bool(com_interesses)}})
    return filtros


def search_declaracoes(
    q: Optional[str] = None,
    *,
    titular_id: Optional[str] = None,
    titular: Optional[str] = None,
    entidade: Optional[str] = None,
    cargo: Optional[str] = None,
    orgao: Optional[str] = None,
    ano: Optional[int] = None,
    natureza: Optional[str] = None,
    com_interesses: Optional[bool] = None,
    sort: str = "recent",
    page: int = 1,
    size: int = 20,
    es: Any = None,
) -> Dict[str, Any]:
    """Pesquisa declarações por texto e pela cascata (entidade/cargo/titular)."""
    cliente = _cliente(es)
    if not cliente:
        return _search_declaracoes_disco(
            q,
            titular_id=titular_id,
            titular=titular,
            entidade=entidade,
            cargo=cargo,
            orgao=orgao,
            ano=ano,
            natureza=natureza,
            page=page,
            size=size,
        )

    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "type": "best_fields",
                    "operator": "and",
                    "fields": ["titular^5", "entidade^3", "cargo^2", "orgao^2", "texto^2"],
                }
            }
        )
    corpo: Dict[str, Any] = {
        "query": {"bool": {"must": must, "filter": _filtros_declaracoes(
            titular_id=titular_id,
            titular=titular,
            entidade=entidade,
            cargo=cargo,
            orgao=orgao,
            ano=ano,
            natureza=natureza,
            com_interesses=com_interesses,
        )}},
        "from": max(0, (max(1, int(page)) - 1) * max(1, int(size))),
        "size": max(1, min(int(size), 200)),
        "track_total_hits": True,
        "_source": {"excludes": ["raw", "secoes", "texto"]},
        "aggs": {
            "anos": {"terms": {"field": "ano", "size": 20, "order": {"_key": "desc"}}},
            "naturezas": {"terms": {"field": "natureza", "size": 10}},
            "entidades": {"terms": {"field": "entidade.keyword", "size": 12}},
            "cargos": {"terms": {"field": "cargo.keyword", "size": 12}},
            "com_interesses": {"filter": {"term": {"tem_registo_interesses": True}}},
        },
    }
    if sort == "name":
        corpo["sort"] = [{"titular.keyword": {"order": "asc"}}, {"ano": {"order": "desc"}}]
    elif sort == "ano":
        corpo["sort"] = [{"ano": {"order": "desc"}}, {"entrega": {"order": "desc"}}]
    else:
        corpo["sort"] = [{"_score": {"order": "desc"}}, {"ano": {"order": "desc"}}, {"entrega": {"order": "desc"}}]

    try:
        resposta = cliente.search(index=esc.EPT_DECLARACOES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001 - índice ainda não criado: ler do disco
        logger.debug("EPT: pesquisa no Elasticsearch falhou (%s); a ler do disco", exc)
        return _search_declaracoes_disco(
            q,
            titular_id=titular_id,
            titular=titular,
            entidade=entidade,
            cargo=cargo,
            orgao=orgao,
            ano=ano,
            natureza=natureza,
            page=page,
            size=size,
        )

    hits = resposta.get("hits") or {}
    agregacoes = resposta.get("aggregations") or {}
    return {
        "total": (hits.get("total") or {}).get("value", 0),
        "items": [{**hit.get("_source", {}), "doc_id": hit.get("_id")} for hit in hits.get("hits") or []],
        "page": max(1, int(page)),
        "size": max(1, int(size)),
        "facetas": {
            "anos": [{"valor": balde.get("key"), "total": balde.get("doc_count")} for balde in (agregacoes.get("anos") or {}).get("buckets") or []],
            "naturezas": [{"valor": balde.get("key"), "total": balde.get("doc_count")} for balde in (agregacoes.get("naturezas") or {}).get("buckets") or []],
            "entidades": [{"valor": balde.get("key"), "total": balde.get("doc_count")} for balde in (agregacoes.get("entidades") or {}).get("buckets") or []],
            "cargos": [{"valor": balde.get("key"), "total": balde.get("doc_count")} for balde in (agregacoes.get("cargos") or {}).get("buckets") or []],
            "com_registo_interesses": (agregacoes.get("com_interesses") or {}).get("doc_count", 0),
        },
    }


def _search_declaracoes_disco(
    q: Optional[str],
    *,
    titular_id: Optional[str] = None,
    titular: Optional[str] = None,
    entidade: Optional[str] = None,
    cargo: Optional[str] = None,
    orgao: Optional[str] = None,
    ano: Optional[int] = None,
    natureza: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> Dict[str, Any]:
    """Pesquisa de recurso no JSONL (sem Elasticsearch)."""
    alvo = ept.normalize_text(q) if q else None
    filtro_titular = ept.normalize_text(titular) if titular else None
    filtro_entidade = ept.normalize_text(entidade) if entidade else None
    filtro_cargo = ept.normalize_text(cargo) if cargo else None
    filtro_orgao = ept.normalize_text(orgao) if orgao else None
    itens: List[Dict[str, Any]] = []
    for documento in _iter_unicos(_declaracoes_jsonl(), "declaracao_id"):
        if titular_id and str(documento.get("titular_id")) != str(titular_id):
            continue
        if ano and int(documento.get("ano") or 0) != int(ano):
            continue
        if natureza and ept.normalize_text(documento.get("natureza")) != ept.normalize_text(natureza):
            continue
        if filtro_titular and filtro_titular not in ept.normalize_text(documento.get("titular")):
            continue
        if filtro_entidade and filtro_entidade not in ept.normalize_text(documento.get("entidade")):
            continue
        if filtro_cargo and filtro_cargo not in ept.normalize_text(documento.get("cargo")):
            continue
        if filtro_orgao and filtro_orgao not in ept.normalize_text(documento.get("orgao")):
            continue
        if alvo:
            texto = " ".join(
                str(documento.get(chave) or "")
                for chave in ("titular", "entidade", "cargo", "orgao", "texto")
            )
            if alvo not in ept.normalize_text(texto):
                continue
        itens.append(_sem_texto_da_fonte(documento))
    itens.sort(key=lambda item: (item.get("ano") or 0, item.get("entrega") or ""), reverse=True)
    inicio = (max(1, int(page)) - 1) * max(1, int(size))
    return {
        "total": len(itens),
        "items": itens[inicio : inicio + max(1, int(size))],
        "page": max(1, int(page)),
        "size": max(1, int(size)),
        "facetas": {},
        "fonte": "disco",
    }


def search_titulares(
    q: Optional[str] = None,
    *,
    entidade: Optional[str] = None,
    cargo: Optional[str] = None,
    orgao: Optional[str] = None,
    page: int = 1,
    size: int = 30,
    es: Any = None,
) -> Dict[str, Any]:
    """Pesquisa titulares já indexados (com a cascata gravada no documento)."""
    cliente = _cliente(es)
    if not cliente:
        return _search_titulares_disco(q, entidade=entidade, cargo=cargo, orgao=orgao, page=page, size=size)
    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "type": "best_fields",
                    "operator": "and",
                    "fields": ["nome^5", "entidades^2", "cargos^2", "orgaos"],
                }
            }
        )
    filtros: List[Dict[str, Any]] = []
    if entidade:
        filtros.append({"term": {"entidades": entidade}})
    if cargo:
        filtros.append({"term": {"cargos": cargo}})
    if orgao:
        filtros.append({"term": {"orgaos": orgao}})
    corpo = {
        "query": {"bool": {"must": must, "filter": filtros}},
        "from": max(0, (max(1, int(page)) - 1) * max(1, int(size))),
        "size": max(1, min(int(size), 200)),
        "track_total_hits": True,
        "sort": [{"_score": {"order": "desc"}}, {"nome.keyword": {"order": "asc"}}],
        "aggs": {
            "entidades": {"terms": {"field": "entidades", "size": 20}},
            "cargos": {"terms": {"field": "cargos", "size": 20}},
            "com_declaracoes": {"filter": {"range": {"declaracoes_total": {"gt": 0}}}},
        },
    }
    try:
        resposta = cliente.search(index=esc.EPT_TITULARES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.debug("EPT: pesquisa de titulares no Elasticsearch falhou (%s)", exc)
        return _search_titulares_disco(q, entidade=entidade, cargo=cargo, orgao=orgao, page=page, size=size)
    hits = resposta.get("hits") or {}
    agregacoes = resposta.get("aggregations") or {}
    return {
        "total": (hits.get("total") or {}).get("value", 0),
        "items": [{**hit.get("_source", {}), "doc_id": hit.get("_id")} for hit in hits.get("hits") or []],
        "page": max(1, int(page)),
        "size": max(1, int(size)),
        "facetas": {
            "entidades": [{"valor": b.get("key"), "total": b.get("doc_count")} for b in (agregacoes.get("entidades") or {}).get("buckets") or []],
            "cargos": [{"valor": b.get("key"), "total": b.get("doc_count")} for b in (agregacoes.get("cargos") or {}).get("buckets") or []],
            "com_declaracoes": (agregacoes.get("com_declaracoes") or {}).get("doc_count", 0),
        },
    }


def _search_titulares_disco(
    q: Optional[str],
    *,
    entidade: Optional[str],
    cargo: Optional[str],
    orgao: Optional[str],
    page: int,
    size: int,
) -> Dict[str, Any]:
    alvo = ept.normalize_name(q) if q else None
    itens: List[Dict[str, Any]] = []
    for documento in _iter_unicos(_titulares_jsonl(), "titular_id"):
        if alvo and alvo not in ept.normalize_name(documento.get("nome")):
            continue
        if entidade and entidade not in (documento.get("entidades") or []):
            continue
        if cargo and cargo not in (documento.get("cargos") or []):
            continue
        if orgao and orgao not in (documento.get("orgaos") or []):
            continue
        itens.append(documento)
    itens.sort(key=lambda item: (item.get("declaracoes_total") or 0, item.get("nome") or ""), reverse=True)
    inicio = (max(1, int(page)) - 1) * max(1, int(size))
    return {
        "total": len(itens),
        "items": itens[inicio : inicio + max(1, int(size))],
        "page": max(1, int(page)),
        "size": max(1, int(size)),
        "facetas": {},
        "fonte": "disco",
    }


# ---------------------------------------------------------------------------
# Fichas
# ---------------------------------------------------------------------------


def declaracao_detail(declaracao_id: str, *, incluir_raw: bool = False, es: Any = None) -> Dict[str, Any]:
    """Ficha de uma declaração (secções, tabelas e registo de interesses)."""
    identificador = str(declaracao_id).strip()
    cliente = _cliente(es)
    if cliente:
        try:
            resposta = cliente.get(index=esc.EPT_DECLARACOES_INDEX, id=f"ept:{identificador}")
            fonte = dict(resposta.get("_source") or {})
            if incluir_raw and not fonte.get("raw"):
                try:
                    fonte["raw"] = ept.fetch_declaration(ept.make_client(), identificador)
                except Exception:  # noqa: BLE001 - o raw é opcional
                    pass
            if not incluir_raw:
                fonte.pop("raw", None)
            return fonte
        except Exception:  # noqa: BLE001 - não indexada: ler do disco ou da API
            pass
    for documento in _iter_unicos(_declaracoes_jsonl(), "declaracao_id"):
        if str(documento.get("declaracao_id")) == identificador:
            documento = dict(documento)
            if not incluir_raw:
                documento.pop("raw", None)
            return documento
    # Último recurso: ler ao vivo (a ficha abre mesmo antes da recolha).
    cliente_http = ept.make_client()
    detalhe = ept.fetch_declaration(cliente_http, identificador)
    documento = ept.normalize_declaration({**detalhe, "id": int(identificador)}, recolhido_em=_now())
    if not incluir_raw:
        documento.pop("raw", None)
    documento["ao_vivo"] = True
    return documento


def titular_detail(
    titular_id: str,
    *,
    ao_vivo: bool = False,
    limite: int = 100,
    es: Any = None,
) -> Dict[str, Any]:
    """Ficha do titular: catálogo, declarações, posições e pessoa do PessoasIQ."""
    identificador = str(titular_id).strip()
    fonte: Dict[str, Any] = {}
    cliente = _cliente(es)
    if cliente:
        try:
            resposta = cliente.get(index=esc.EPT_TITULARES_INDEX, id=identificador)
            fonte = dict(resposta.get("_source") or {})
        except Exception:  # noqa: BLE001
            pass
    if not fonte:
        for documento in _iter_unicos(_titulares_jsonl(), "titular_id"):
            if str(documento.get("titular_id")) == identificador:
                fonte = dict(documento)
    entrada = (read_manifest().get("titulares") or {}).get(identificador) or {}
    nome = fonte.get("nome") or entrada.get("nome") or ""
    if not nome:
        encontrado = _titular_do_catalogo(identificador)
        nome = (encontrado or {}).get("nome") or ""

    declaracoes = search_declaracoes(titular_id=identificador, size=max(1, min(int(limite), 200)), es=cliente)
    if ao_vivo and not declaracoes.get("items"):
        cliente_http = ept.make_client()
        metas = ept.fetch_declarations(cliente_http, identificador)
        documentos = []
        for meta in metas[: int(limite)]:
            try:
                detalhe = ept.fetch_declaration(cliente_http, meta["declaracao_id"])
                documentos.append(
                    ept.normalize_declaration(
                        {**detalhe, "id": int(meta["declaracao_id"])}, recolhido_em=_now()
                    )
                )
                documentos[-1].pop("raw", None)
            except Exception as exc:  # noqa: BLE001
                logger.debug("EPT: declaração %s não lida ao vivo (%s)", meta.get("declaracao_id"), exc)
        declaracoes = {
            "total": len(documentos),
            "items": [_sem_texto_da_fonte(documento) for documento in documentos],
            "ao_vivo": True,
        }

    posicoes = [item for item in _iter_jsonl(_titularidades_jsonl()) if str(item.get("titular_id")) == identificador]
    return {
        "titular": {
            "titular_id": identificador,
            "nome": nome,
            "nome_normalizado": ept.normalize_name(nome),
            **{chave: valor for chave, valor in fonte.items() if chave not in ("nome", "nome_normalizado")},
        },
        "posicoes": posicoes,
        "declaracoes": declaracoes,
        "pessoa": match_pessoa(nome) if nome else {"encontrado": False, "candidatos": []},
        "fonte": "entidade-transparencia",
        "fonte_url": ept.BASE_WEB,
    }


# ---------------------------------------------------------------------------
# Ligação ao PessoasIQ («ficha do político»)
# ---------------------------------------------------------------------------


def _pontuacao_nome(alvo: str, candidato: str) -> float:
    """Semelhança entre dois nomes, tolerante a nomes do meio em falta.

    O PessoasIQ guarda muitas vezes o nome curto («António Costa») e a EPT o
    nome completo («António Luís Santos da Costa»). Se todos os tokens do nome
    curto estiverem no nome completo, é uma correspondência forte — não uma
    simples semelhança de caracteres.

    O último token manda: em português é o apelido. «António Costa» está
    contido em «António Costa Rodrigues», mas é outra pessoa — sem esta regra,
    qualquer nome curto empatava com dezenas de homónimos.
    """
    tokens_alvo = alvo.split()
    tokens_candidato = candidato.split()
    a = set(tokens_alvo)
    c = set(tokens_candidato)
    if not a or not c:
        return 0.0
    mesmo_apelido = tokens_alvo[-1] == tokens_candidato[-1]
    if (c <= a or a <= c) and min(len(a), len(c)) >= 2:
        # Subconjunto de tokens com o mesmo apelido: correspondência forte e
        # com a mesma pontuação, seja o nome maior ou menor. A pontuação não
        # pode crescer à medida que o nome encurta — é isso que fazia
        # «António Augusto da Costa» ganhar a «António Luís Santos da Costa».
        return 0.96 if mesmo_apelido else 0.85
    return difflib.SequenceMatcher(None, alvo, candidato).ratio()


def _termos_de_pesquisa(nome: str) -> List[str]:
    """Variantes do nome por ordem de especificidade (com e sem partículas)."""
    tokens = [token for token in ept.normalize_name(nome).split() if token]
    particulas = {"de", "da", "do", "das", "dos", "e"}
    uteis = [token for token in tokens if token not in particulas]
    variantes: List[str] = []
    for termo in (
        " ".join(tokens),
        " ".join(uteis),
        " ".join([uteis[0], uteis[-1]]) if len(uteis) >= 2 else "",
        " ".join(uteis[:2] + [uteis[-1]]) if len(uteis) >= 3 else "",
        " ".join(uteis[:3]) if len(uteis) >= 3 else "",
    ):
        if termo and termo not in variantes:
            variantes.append(termo)
    return variantes


def match_pessoa(nome: Optional[str], *, limiar: float = 0.88, es: Any = None) -> Dict[str, Any]:
    """Liga um nome da EPT a uma ficha de `finance_people` (por semelhança).

    A EPT não publica o NIF do titular. Exige-se uma semelhança alta (ou que o
    nome curto do PessoasIQ esteja contido no nome completo da EPT) para não
    confundir homónimos; sem correspondência devolve os melhores candidatos.
    """
    if not nome:
        return {"encontrado": False, "candidatos": []}
    alvo = ept.normalize_name(nome)
    vistos: set[str] = set()
    candidatos: List[Dict[str, Any]] = []
    for termo in _termos_de_pesquisa(nome):
        resultado = esc.search_people(q=termo, size=10, es=es)
        for pessoa in resultado.get("items") or []:
            if pessoa.get("is_company"):
                continue
            chave = str(pessoa.get("nif") or pessoa.get("name"))
            if chave in vistos:
                continue
            vistos.add(chave)
            candidato = ept.normalize_name(pessoa.get("name"))
            candidatos.append(
                {
                    "nif": pessoa.get("nif"),
                    "nome": pessoa.get("name"),
                    "fonte": pessoa.get("source"),
                    "partido": (pessoa.get("metadata") or {}).get("party"),
                    "pontuacao": round(_pontuacao_nome(alvo, candidato), 3),
                    "exato": candidato == alvo,
                }
            )
        if candidatos:
            break
    candidatos.sort(key=lambda item: (item["exato"], item["pontuacao"]), reverse=True)
    melhor = candidatos[0] if candidatos and candidatos[0]["pontuacao"] >= limiar else None
    ambiguo = bool(
        melhor
        and not melhor.get("exato")
        and len([c for c in candidatos if abs(c["pontuacao"] - melhor["pontuacao"]) < 1e-9]) > 1
    )
    return {"encontrado": bool(melhor), "pessoa": melhor, "candidatos": candidatos[:5], "ambiguo": ambiguo}


_AMBIGUIDADE_EPSILON = 0.02
_NOME_CACHE: Dict[str, Any] = {}
_NOME_CACHE_TTL = 300.0


def _pontuar_titulares(alvo: str) -> List[Dict[str, Any]]:
    """Todos os titulares do catálogo pontuados contra um nome normalizado.

    A varredura é sobre o catálogo completo (12 372 nomes, ~0,5 s) e não sobre
    os primeiros resultados do Elasticsearch: a pesquisa por relevância
    devolvia um subconjunto diferente conforme o índice, e o mesmo nome do
    PessoasIQ chegava a titulares distintos no PC e na VM. A regra de
    subconjunto de tokens («António Costa» ⊂ «António Luís Santos da Costa»)
    exige ver todos os candidatos, não os mais relevantes.
    """
    agora = time.time()
    entrada = _NOME_CACHE.get(alvo)
    if entrada and agora - entrada[0] < _NOME_CACHE_TTL:
        return entrada[1]
    fontes: List[Dict[str, Any]] = list(_ler_cache_bruta("titulares") or [])
    if not fontes:
        fontes = list(_iter_unicos(_titulares_jsonl(), "titular_id"))
    pontuados: List[Dict[str, Any]] = []
    for fonte in fontes:
        titular_id = fonte.get("id") or fonte.get("titular_id")
        nome_fonte = fonte.get("nome")
        if not titular_id or not nome_fonte:
            continue
        normalizado = ept.normalize_name(nome_fonte)
        pontuados.append(
            {
                "titular_id": str(titular_id),
                "nome": nome_fonte,
                "pontuacao": round(_pontuacao_nome(alvo, normalizado), 3),
                "exato": normalizado == alvo,
            }
        )
    # O nome exato ganha sempre; depois a pontuação e, no empate, o nome mais
    # completo (a EPT guarda nomes completos; o PessoasIQ, muitas vezes, não).
    pontuados.sort(
        key=lambda item: (item["exato"], item["pontuacao"], len(item["nome"].split())),
        reverse=True,
    )
    _NOME_CACHE[alvo] = (agora, pontuados)
    return pontuados


def _titulares_por_nome(
    nome: str,
    *,
    limiar: float = 0.88,
    es: Any = None,
    limite: int = 5,
) -> List[Dict[str, Any]]:
    """Titulares da EPT parecidos com um nome, do mais para o menos parecido."""
    alvo = ept.normalize_name(nome)
    if not alvo:
        return []
    candidatos = [candidato for candidato in _pontuar_titulares(alvo) if candidato["pontuacao"] >= limiar]
    if not candidatos:
        # Catálogo indisponível: resta a pesquisa no índice.
        for termo in _termos_de_pesquisa(nome):
            resultado = search_titulares(q=termo, size=25, es=es)
            for item in resultado.get("items") or []:
                normalizado = ept.normalize_name(item.get("nome"))
                pontuacao = _pontuacao_nome(alvo, normalizado)
                if pontuacao >= limiar:
                    candidatos.append(
                        {
                            "titular_id": str(item.get("titular_id")),
                            "nome": item.get("nome"),
                            "pontuacao": round(pontuacao, 3),
                            "exato": normalizado == alvo,
                        }
                    )
            if candidatos:
                candidatos.sort(
                    key=lambda item: (item["exato"], item["pontuacao"], len(item["nome"].split())),
                    reverse=True,
                )
                break
    return candidatos[: max(1, int(limite))]


def _titular_por_nome(nome: str, *, limiar: float = 0.88, es: Any = None) -> Optional[Dict[str, Any]]:
    """Melhor titular da EPT para um nome de pessoa (também tolera nomes curtos)."""
    candidatos = _titulares_por_nome(nome, limiar=limiar, es=es, limite=1)
    return candidatos[0] if candidatos else None


def _homonimos(candidatos: List[Dict[str, Any]]) -> bool:
    """Dois candidatos praticamente empatados: o nome não decide sozinho.

    Um nome exato não é ambíguo, mesmo que outros nomes parecidos empatem na
    pontuação: «Adérito Manuel Pereira dos Santos» é ele mesmo.
    """
    if len(candidatos) < 2 or candidatos[0].get("exato"):
        return False
    return abs(candidatos[0]["pontuacao"] - candidatos[1]["pontuacao"]) <= _AMBIGUIDADE_EPSILON


def pessoa_declaracoes(nif: str, *, size: int = 100, es: Any = None) -> Dict[str, Any]:
    """Declarações da EPT ligadas a uma pessoa do PessoasIQ (por nome).

    A EPT não publica NIF: a ligação é por nome. Quando dois titulares ficam
    praticamente empatados («Antonio Costa» serve tanto um primeiro-ministro
    como um deputado homónimo), devolve `ambiguo: true` com os candidatos, em
    vez de escolher um deles em silêncio.
    """
    pessoa = esc.get_person_by_nif(str(nif), es=es)
    if pessoa.get("error"):
        return {"nif": str(nif), "pessoa": None, "total": 0, "items": [], "error": pessoa["error"]}
    nome = pessoa.get("name") or ""
    limite = max(1, min(int(size), 200))
    candidatos = _titulares_por_nome(nome, es=es, limite=6) if nome else []
    total_candidatos = len(_titulares_por_nome(nome, es=es, limite=10_000)) if nome else 0
    ambiguo = _homonimos(candidatos)
    # Com homónimos empatados não se escolhe ninguém: mostrar as declarações de
    # um «António … da Costa» ao calhas na ficha de outro sería pior do que não
    # mostrar nada. Ficam os candidatos para a pessoa decidir.
    titular = None if ambiguo else (candidatos[0] if candidatos else None)
    if ambiguo:
        declaracoes: Dict[str, Any] = {"total": 0, "items": []}
    elif titular and titular.get("titular_id"):
        declaracoes = search_declaracoes(titular_id=titular["titular_id"], size=limite, es=es)
    else:
        declaracoes = search_declaracoes(titular=nome, size=limite, es=es)
        if not declaracoes.get("items"):
            # Ocasionalmente o nome do PessoasIQ tem partículas a mais; procura-se
            # pelo nome normalizado exato antes de desistir.
            declaracoes = _search_declaracoes_por_nome(nome, size=size, es=es)
    if not ambiguo and titular and titular.get("titular_id") and not declaracoes.get("items"):
        # Titular já identificado mas ainda não recolhido: lê-se a lista ao vivo,
        # para que a ficha do político não fique vazia a meio de uma recolha.
        try:
            cliente = ept.make_client()
            metas = ept.fetch_declarations(cliente, str(titular["titular_id"]))[:limite]
            declaracoes = {"total": len(metas), "items": metas, "ao_vivo": True}
        except Exception as exc:  # noqa: BLE001 - sem rede, fica o que há em disco
            logger.debug("EPT: declarações de %s não lidas ao vivo (%s)", titular.get("titular_id"), exc)
    if not ambiguo and not titular and declaracoes.get("items"):
        primeira = declaracoes["items"][0]
        titular = {"titular_id": primeira.get("titular_id"), "nome": primeira.get("titular")}
    return {
        "nif": str(nif),
        "pessoa": {"nif": pessoa.get("nif"), "nome": nome, "partido": (pessoa.get("metadata") or {}).get("party")},
        "titular": titular,
        "ambiguo": ambiguo,
        "candidatos": candidatos,
        "total_candidatos": total_candidatos,
        "total": declaracoes.get("total", 0),
        "items": declaracoes.get("items") or [],
        "ao_vivo": bool(declaracoes.get("ao_vivo")),
        "fonte": "entidade-transparencia",
    }


def _search_declaracoes_por_nome(nome: str, *, size: int = 100, es: Any = None) -> Dict[str, Any]:
    cliente = _cliente(es)
    if not cliente:
        return _search_declaracoes_disco(None, titular=nome, page=1, size=size)
    corpo = {
        "query": {"term": {"titular_normalizado": ept.normalize_name(nome)}},
        "size": max(1, min(int(size), 200)),
        "track_total_hits": True,
        "sort": [{"ano": {"order": "desc"}}, {"entrega": {"order": "desc"}}],
        "_source": {"excludes": ["raw", "secoes", "texto"]},
    }
    try:
        resposta = cliente.search(index=esc.EPT_DECLARACOES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.debug("EPT: pesquisa por nome falhou (%s)", exc)
        return _search_declaracoes_disco(None, titular=nome, page=1, size=size)
    hits = resposta.get("hits") or {}
    return {
        "total": (hits.get("total") or {}).get("value", 0),
        "items": [{**hit.get("_source", {}), "doc_id": hit.get("_id")} for hit in hits.get("hits") or []],
    }


# ---------------------------------------------------------------------------
# Metamodelo, estatísticas e exportação
# ---------------------------------------------------------------------------


def _contagem_indice(indice: str, cliente: Any = None) -> Optional[int]:
    cliente = cliente or esc.get_es_client()
    if not cliente:
        return None
    try:
        resposta = cliente.count(index=indice)
        return int(resposta.get("count") or 0)
    except Exception:  # noqa: BLE001
        return None


def stats(es: Any = None) -> Dict[str, Any]:
    """Volumetria do módulo, juntando o índice ao que está em disco.

    Uma recolha longa deixa o índice atrás do disco; as contagens mostram o
    maior dos dois (nunca andam para trás) e `indice_desatualizado` diz que
    falta indexar.
    """
    cliente = _cliente(es)
    manifest = read_manifest()
    totais = dict(manifest.get("totais") or {})
    titulares_disco = len(manifest.get("titulares") or {})
    declaracoes_disco = int(totais.get("declaracoes") or 0)
    titularidades_disco = _contar_linhas(_titularidades_jsonl())
    declaracoes_indice = _contagem_indice(esc.EPT_DECLARACOES_INDEX, cliente)
    titulares_indice = _contagem_indice(esc.EPT_TITULARES_INDEX, cliente)
    titularidades_indice = _contagem_indice(esc.EPT_TITULARIDADES_INDEX, cliente)
    com_interesses: Optional[int] = totais.get("com_registo_interesses")
    if cliente:
        try:
            com_interesses = int(
                cliente.count(
                    index=esc.EPT_DECLARACOES_INDEX,
                    query={"term": {"tem_registo_interesses": True}},
                ).get("count")
                or 0
            )
        except Exception:  # noqa: BLE001 - índice ainda não criado
            com_interesses = None
    return {
        "titulares": max(titulares_disco, titulares_indice or 0),
        "declaracoes": max(declaracoes_disco, declaracoes_indice or 0),
        "titularidades": max(titularidades_disco, titularidades_indice or 0),
        "entidades": (manifest.get("catalogo") or {}).get("entidades"),
        "cargos": (manifest.get("catalogo") or {}).get("cargos"),
        "orgaos": (manifest.get("catalogo") or {}).get("orgaos"),
        "com_registo_interesses": com_interesses,
        "atualizado_em": manifest.get("atualizado_em"),
        "fonte_indexada": cliente is not None,
        "titulares_indexados": titulares_indice,
        "declaracoes_indexadas": declaracoes_indice,
        "indice_desatualizado": bool(cliente)
        and ((titulares_indice or 0) < titulares_disco or (declaracoes_indice or 0) < declaracoes_disco),
    }


def meta() -> Dict[str, Any]:
    """Proveniência, pastas, índice e endpoints do módulo."""
    manifest = read_manifest()
    cliente = esc.get_es_client()
    return {
        "fonte": "Entidade para a Transparência",
        "fonte_url": ept.BASE_WEB,
        "api_url": ept.BASE_API,
        "descricao": (
            "Declarações únicas de titulares de cargos políticos e altos cargos "
            "públicos: facto determinante, dados pessoais, rendimentos, ativo, "
            "passivo e registo de interesses."
        ),
        "cascata": ["entidade", "cargo", "titular"],
        "pasta": str(data_dir()),
        "catalogo": str(catalogo_dir()),
        "normalizados": str(normalized_dir()),
        "indices": [
            esc.EPT_TITULARES_INDEX,
            esc.EPT_TITULARIDADES_INDEX,
            esc.EPT_DECLARACOES_INDEX,
            esc.EPT_RECOLHAS_INDEX,
        ],
        "manifesto": {
            "atualizado_em": manifest.get("atualizado_em"),
            "totais": manifest.get("totais") or {},
            "catalogo": manifest.get("catalogo") or {},
            "titulares": len(manifest.get("titulares") or {}),
        },
        "endpoints": {
            "entidades": f"{ept.BASE_API}{ept.PATH_ENTITIES}",
            "cargos": f"{ept.BASE_API}{ept.PATH_ROLES}",
            "orgaos": f"{ept.BASE_API}{ept.PATH_BOARDS}",
            "titulares": f"{ept.BASE_API}{ept.PATH_HOLDERS}",
            "titularidades": f"{ept.BASE_API}{ept.PATH_POSITIONS}",
            "declaracoes": f"{ept.BASE_API}{ept.PATH_DECLARATIONS}",
            "declaracao": f"{ept.BASE_API}{ept.PATH_DECLARATION}",
        },
        "naturezas": NATUREZAS,
        "estados": ESTADOS,
        "elasticsearch": cliente is not None,
    }


def csv_bytes(**filtros: Any) -> bytes:
    """Exporta a pesquisa de declarações em CSV (até 10 000 linhas)."""
    itens: List[Dict[str, Any]] = []
    pagina = 1
    while len(itens) < 10_000:
        resultado = search_declaracoes(page=pagina, size=200, **filtros)
        lote = resultado.get("items") or []
        itens.extend(lote)
        total = int(resultado.get("total") or 0)
        if not lote or len(itens) >= total:
            break
        pagina += 1
    saida = io.StringIO()
    campos = [
        "declaracao_id",
        "ano",
        "natureza",
        "estado",
        "titular",
        "entidade",
        "orgao",
        "cargo",
        "inicio",
        "fim",
        "entrega",
        "tem_registo_interesses",
    ]
    escritor = csv.DictWriter(saida, fieldnames=campos, extrasaction="ignore")
    escritor.writeheader()
    for item in itens:
        escritor.writerow({campo: item.get(campo) for campo in campos})
    return saida.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Trabalhos em segundo plano
# ---------------------------------------------------------------------------


def _prune_jobs() -> None:
    if len(_JOBS) <= _JOBS_KEEP:
        return
    antigos = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""))
    for job in antigos[: len(_JOBS) - _JOBS_KEEP]:
        if job.get("status") == _RUNNING:
            continue
        _JOBS.pop(str(job["job_id"]), None)


def start_job(tipo: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Arranca «recolher» (catálogo + declarações) ou «indexar» (JSONL → ES)."""
    if tipo not in TIPOS_JOB:
        raise ValueError(f"Tipo de trabalho desconhecido: {tipo}")
    with _JOBS_LOCK:
        for job in _JOBS.values():
            if job.get("status") == _RUNNING and job.get("tipo") == tipo:
                return {
                    "job_id": job["job_id"],
                    "tipo": tipo,
                    "status": _RUNNING,
                    "already_running": True,
                    "message": "Já existe um trabalho deste tipo a correr.",
                }
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
                "titulares_total": 0,
                "titulares_done": 0,
                "declaracoes": 0,
                "registos": 0,
                "current": None,
            },
            "result": None,
            "error": None,
        }
        _JOBS[job["job_id"]] = job
        _prune_jobs()
    threading.Thread(target=_run_job, args=(job,), name=f"ept-{tipo}", daemon=True).start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    try:
        payload = job["payload"]
        progresso = job["progress"]
        if job["tipo"] == "recolher":
            resultado = recolher(
                entidade_id=payload.get("entidade_id"),
                cargo_id=payload.get("cargo_id"),
                orgao_id=payload.get("orgao_id"),
                titular_id=payload.get("titular_id"),
                limite_titulares=payload.get("limite_titulares"),
                limite_declaracoes=payload.get("limite_declaracoes"),
                pausa=float(payload.get("pausa") or ept.PAUSA),
                forcar=bool(payload.get("forcar")),
                indexar_no_fim=bool(payload.get("indexar")),
                progresso=progresso,
            )
        elif job["tipo"] == "exportar":
            resultado = exportar_entidades_json(
                payload.get("entidades") or None,
                progresso=progresso,
            )
        elif job["tipo"] == "validar":
            resultado = validar(
                pausa=float(payload.get("pausa") or ept.PAUSA),
                limite_titulares=payload.get("limite_titulares", 0),
                limite_declaracoes=payload.get("limite_declaracoes"),
                progresso=progresso,
            )
        else:
            resultado = indexar(forcar=bool(payload.get("forcar")), progresso=progresso)
        job["result"] = resultado
        job["status"] = "error" if resultado.get("error") else "done"
        erros = resultado.get("errors") or []
        if erros:
            job["error"] = f"{len(erros)} item(ns) com erro"
        job["finished_at"] = _now()
        progresso["phase"] = "concluído"
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Trabalho da Entidade para a Transparência falhou")
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
