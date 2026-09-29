"""Recolha massiva de dados societários para JSON e indexação no Elasticsearch.

O módulo societário (`api/societario_service.py`) recolhe **uma** entidade de cada
vez, a pedido, e indexa logo. Este módulo trata da recolha em **lote**:

1. escolher os alvos por **ano dos contratos** e/ou por **empresa**
   (`societario_targets_filtered`);
2. recolher as publicações de cada entidade (reCAPTCHA via 2captcha) e guardar
   **um ficheiro JSON por entidade** em `SOCIETARIO_EXPORT_DIR`
   (por omissão `finance-llm/exports/societario/`);
3. indexar esses ficheiros em `finance_publicacoes_mj` (e alimentar o PessoasIQ)
   numa passagem separada — a recolha e a indexação não ficam presas uma à outra.

Cada ficheiro tem o cabeçalho antes da lista, para se poder listar/inspecionar sem
carregar as publicações todas:

```json
{"nif": "...", "name": "...", "collected_at": "...", "criteria": {...},
 "total": 12, "items": [{...}]}
```

Os trabalhos correm em segundo plano (uma thread por trabalho, com registo de
progresso) e o manifesto `_manifest.json` guarda o resumo do que está exportado.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from api import societario_service as societario

logger = logging.getLogger(__name__)

#: Pasta dos ficheiros JSON (configurável por variável de ambiente).
EXPORT_DIR_ENV = "SOCIETARIO_EXPORT_DIR"
_DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[1] / "exports" / "societario"
_MANIFEST = "_manifest.json"

#: Trabalhos de recolha massiva (id → estado). Mantêm-se os últimos `_JOBS_KEEP`.
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 20
_RUNNING = "running"


# ---------------------------------------------------------------------------
# Pasta e ficheiros
# ---------------------------------------------------------------------------

def export_dir() -> Path:
    """Pasta dos ficheiros JSON (criada se não existir)."""
    raw = (os.environ.get(EXPORT_DIR_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else _DEFAULT_EXPORT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_path(nif: str) -> Path:
    """Caminho do ficheiro JSON de uma entidade."""
    return export_dir() / f"societario-{str(nif).strip()}.json"


def _manifest_path() -> Path:
    return export_dir() / _MANIFEST


def _read_manifest() -> Dict[str, Any]:
    path = _manifest_path()
    if not path.exists():
        return {"generated_at": None, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - manifesto corrompido não pode travar o módulo
        logger.warning("Manifesto de exportação ilegível (%s): %s", path, exc)
        return {"generated_at": None, "files": {}}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"generated_at": None, "files": {}}
    return data


def _write_manifest(manifest: Dict[str, Any]) -> None:
    manifest["generated_at"] = _now()
    tmp = _manifest_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_manifest_path())


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_export(
    nif: str,
    name: Optional[str],
    items: List[Dict[str, Any]],
    criteria: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grava (ou junta) as publicações de uma entidade no ficheiro JSON.

    Uma nova recolha **junta** ao que já lá estava (chave: ``pub_id``), pelo que
    repetir a recolha de uma entidade não perde o que já existia nem duplica.
    """
    nif = str(nif).strip()
    if not nif:
        raise ValueError("NIF da entidade em falta.")

    existentes: List[Dict[str, Any]] = []
    anteriores: Dict[str, Any] = {}
    atual = export_path(nif)
    if atual.exists():
        anterior = read_export(nif)
        existentes = list(anterior.get("items") or [])
        anteriores = {k: v for k, v in anterior.items() if k != "items"}

    por_id: Dict[str, Dict[str, Any]] = {}
    for item in [*existentes, *items]:
        chave = str(item.get("pub_id") or "").strip()
        if not chave:
            continue
        por_id[chave] = item
    merged = sorted(
        por_id.values(),
        key=lambda item: str(item.get("data_publicacao") or ""),
        reverse=True,
    )

    payload = {
        "nif": nif,
        "name": (name or anteriores.get("name") or "").strip() or None,
        "collected_at": _now(),
        "first_collected_at": anteriores.get("first_collected_at") or anteriores.get("collected_at") or _now(),
        "criteria": {**(anteriores.get("criteria") or {}), **(criteria or {})} or None,
        "total": len(merged),
        "items": merged,
    }
    path = export_path(nif)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

    manifest = _read_manifest()
    manifest["files"][nif] = {
        "nif": nif,
        "name": payload["name"],
        "file": path.name,
        "total": len(merged),
        "new": len(items),
        "bytes": path.stat().st_size,
        "updated_at": payload["collected_at"],
    }
    _write_manifest(manifest)
    return {
        "nif": nif,
        "file": str(path),
        "total": len(merged),
        "added": len(items),
        "duplicates": max(0, len(items) - (len(merged) - len(existentes))),
    }


def read_export(nif: str, *, limit_items: Optional[int] = None) -> Dict[str, Any]:
    """Lê o ficheiro JSON de uma entidade.

    ``limit_items`` corta a lista devolvida (pré-visualização na UI) sem alterar o
    ficheiro em disco.
    """
    path = export_path(nif)
    if not path.exists():
        return {"error": f"Sem ficheiro exportado para o NIF {nif}.", "nif": str(nif)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Ficheiro ilegível: {exc}", "nif": str(nif)}
    if not isinstance(data, dict):
        return {"error": "Formato inesperado do ficheiro.", "nif": str(nif)}
    data.setdefault("nif", str(nif))
    if limit_items is not None:
        total = len(data.get("items") or [])
        data["items"] = list(data.get("items") or [])[: max(0, int(limit_items))]
        data["items_total"] = total
    return data


def delete_export(nif: str) -> Dict[str, Any]:
    """Apaga o ficheiro JSON de uma entidade (e a entrada no manifesto)."""
    path = export_path(nif)
    existia = path.exists()
    if existia:
        path.unlink()
    manifest = _read_manifest()
    manifest["files"].pop(str(nif).strip(), None)
    _write_manifest(manifest)
    return {"nif": str(nif), "removed": existia}


def list_exports() -> Dict[str, Any]:
    """Lista os ficheiros exportados (do manifesto, com tamanho real no disco)."""
    manifest = _read_manifest()
    items: List[Dict[str, Any]] = []
    changed = False
    for nif, entry in list(manifest["files"].items()):
        path = export_dir() / str(entry.get("file") or f"societario-{nif}.json")
        if not path.exists():
            manifest["files"].pop(nif, None)
            changed = True
            continue
        stat = path.stat()
        items.append(
            {
                "nif": nif,
                "name": entry.get("name"),
                "file": path.name,
                "total": entry.get("total"),
                "bytes": stat.st_size,
                "updated_at": entry.get("updated_at"),
                "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    if changed:
        _write_manifest(manifest)
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {
        "dir": str(export_dir()),
        "total": len(items),
        "publications": sum(int(item.get("total") or 0) for item in items),
        "bytes": sum(int(item.get("bytes") or 0) for item in items),
        "generated_at": manifest.get("generated_at"),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Alvos (anos dos contratos + empresas)
# ---------------------------------------------------------------------------

def years() -> Dict[str, Any]:
    """Anos de contratos disponíveis para filtrar os alvos."""
    from api.elasticsearch_client import contract_years

    return contract_years()


def search_companies(q: str, *, limit: int = 10) -> Dict[str, Any]:
    """Empresas a pesquisar para recolher dados societários (firma ou NIF).

    Junta o cadastro de entidades (contratos/valor) ao estado deste módulo:
    publicações já indexadas e ficheiro JSON exportado, para a UI dizer logo
    «já existe» ou «por obter».
    """
    from api.elasticsearch_client import societario_targets_filtered

    termo = (q or "").strip()
    if len(termo) < 2:
        return {"q": termo, "items": []}
    res = societario_targets_filtered(q=termo, limit=limit, exclude_collected=False)
    if res.get("error"):
        return {"q": termo, "items": [], "error": res["error"]}

    manifest = _read_manifest().get("files") or {}
    items: List[Dict[str, Any]] = []
    for item in res.get("items") or []:
        nif = str(item.get("nif") or "")
        exportado = manifest.get(nif) or {}
        items.append(
            {
                **item,
                "exported": bool(exportado) and export_path(nif).exists(),
                "exported_total": exportado.get("total"),
                "exported_updated_at": exportado.get("updated_at"),
            }
        )
    return {"q": termo, "items": items, "total": len(items)}


def company_overview(nif: str, *, limit_items: int = 20) -> Dict[str, Any]:
    """Ficha de uma empresa no módulo de recolha: o que existe e como obtê-lo.

    Devolve o cadastro (nome, contratos, valor), o que já está no índice
    `finance_publicacoes_mj` e o ficheiro JSON exportado (com pré-visualização).
    Sem ficheiro, cai nas publicações do índice — «ver os dados» funciona sempre
    que exista alguma coisa, venha ela de onde vier.
    """
    from api.elasticsearch_client import company_publicacoes as _company_publicacoes
    from api.elasticsearch_client import get_company_by_nif, get_entity_by_nif, societario_counts_by_nif

    chave = str(nif or "").strip()
    if not chave:
        return {"error": "Indique o NIF/NIPC da empresa."}

    entidade: Dict[str, Any] = {}
    try:
        entidade = get_entity_by_nif(chave) or {}
    except Exception as exc:  # noqa: BLE001 - o cadastro é enriquecimento
        logger.debug("Cadastro de entidades falhou para %s: %s", chave, exc)
    if not entidade.get("name"):
        try:
            contrato = get_company_by_nif(chave) or {}
            if contrato.get("name"):
                entidade = {**contrato, **{k: v for k, v in entidade.items() if v}}
        except Exception as exc:  # noqa: BLE001
            logger.debug("Cadastro de contratos falhou para %s: %s", chave, exc)

    indexadas = int(societario_counts_by_nif([chave]).get(chave, 0))
    manifesto = (_read_manifest().get("files") or {}).get(chave) or {}
    tem_ficheiro = bool(manifesto) and export_path(chave).exists()

    itens: List[Dict[str, Any]] = []
    total_itens = 0
    origem = "none"
    if tem_ficheiro:
        ficheiro = read_export(chave)
        if not ficheiro.get("error"):
            todos = list(ficheiro.get("items") or [])
            total_itens = len(todos)
            itens = todos[: max(0, int(limit_items))]
            origem = "export" if itens else "none"
    if not itens and indexadas:
        publicacoes = _company_publicacoes(chave, size=max(1, min(int(limit_items or 20), 200))) or {}
        itens = list(publicacoes.get("items") or [])
        total_itens = int(publicacoes.get("total") or len(itens))
        origem = "index" if itens else "none"

    return {
        "nif": chave,
        "name": entidade.get("name") or manifesto.get("name") or None,
        "contracts_count": entidade.get("contracts_count"),
        "total_value": entidade.get("total_value"),
        "indexed_publications": indexadas,
        "exported": tem_ficheiro,
        "exported_total": manifesto.get("total"),
        "exported_updated_at": manifesto.get("updated_at"),
        "source": origem,
        "items": itens,
        "items_total": total_itens,
        "has_data": bool(indexadas or tem_ficheiro),
    }


def targets(
    *,
    ano_ini: Optional[int] = None,
    ano_fim: Optional[int] = None,
    papel: str = "ambos",
    q: Optional[str] = None,
    nifs: Optional[Iterable[str]] = None,
    min_contracts: int = 1,
    min_value: Optional[float] = None,
    exclude_collected: bool = True,
    limit: int = 50,
    from_: int = 0,
) -> Dict[str, Any]:
    """Entidades alvo da recolha, filtradas por ano de contrato e por empresa."""
    from api.elasticsearch_client import societario_targets_filtered

    if ano_ini and ano_fim and int(ano_ini) > int(ano_fim):
        raise ValueError("O ano inicial não pode ser posterior ao final.")
    return societario_targets_filtered(
        ano_ini=ano_ini,
        ano_fim=ano_fim,
        papel=papel,
        q=q,
        nifs=nifs,
        min_contracts=min_contracts,
        min_value=min_value,
        exclude_collected=exclude_collected,
        limit=limit,
        from_=from_,
    )


# ---------------------------------------------------------------------------
# Indexação dos ficheiros exportados
# ---------------------------------------------------------------------------

def ingest_exports(
    *,
    nifs: Optional[Iterable[str]] = None,
    with_people: bool = True,
    only_missing: bool = False,
) -> Dict[str, Any]:
    """Indexa no Elasticsearch os ficheiros JSON exportados.

    Se ``nifs`` for indicado, indexa só esses; caso contrário percorre todos os
    ficheiros do manifesto. ``only_missing`` salta as entidades cujo ficheiro já
    tem tantas publicações no índice como no disco.
    """
    manifesto = list_exports()
    disponiveis = {str(item["nif"]): item for item in manifesto["items"]}
    alvo: List[str] = [str(n) .strip() for n in (nifs or []) if str(n).strip()] if nifs else list(disponiveis)
    if nifs and not alvo:
        return {"entities": 0, "indexed": 0, "errors": [], "message": "Nenhum NIF indicado."}

    indexado: Dict[str, int] = {}
    if only_missing:
        from api.elasticsearch_client import societario_counts_by_nif

        indexado = societario_counts_by_nif(alvo)

    detalhes: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    total_indexed = 0
    total_people = 0
    entidades = 0

    for nif in alvo:
        entrada = disponiveis.get(nif) or {}
        esperado = int(entrada.get("total") or 0)
        if only_missing and esperado and indexado.get(nif, 0) >= esperado:
            detalhes.append({"nif": nif, "skipped": True, "reason": "já indexado", "publications": esperado})
            continue
        ficheiro = read_export(nif)
        if ficheiro.get("error"):
            errors.append({"nif": nif, "error": ficheiro["error"]})
            continue
        items = ficheiro.get("items") or []
        if not items:
            detalhes.append({"nif": nif, "skipped": True, "reason": "ficheiro sem publicações"})
            continue
        try:
            resultado = societario.ingest(items, replace_for_nif=nif) if with_people else _ingest_only(items, nif)
        except Exception as exc:  # noqa: BLE001 - um ficheiro mau não trava o lote
            logger.exception("Falha a indexar o ficheiro de %s", nif)
            errors.append({"nif": nif, "error": str(exc)})
            continue
        if resultado.get("error"):
            errors.append({"nif": nif, "error": resultado["error"]})
            continue
        entidades += 1
        total_indexed += int(resultado.get("indexed_count") or 0)
        pessoas = resultado.get("people") or {}
        total_people += int(pessoas.get("indexed_count") or 0)
        detalhes.append(
            {
                "nif": nif,
                "name": ficheiro.get("name") or entrada.get("name"),
                "publications": resultado.get("indexed_count"),
                "people": pessoas.get("indexed_count"),
                "deleted_stale": resultado.get("deleted_stale"),
            }
        )

    return {
        "entities": entidades,
        "requested": len(alvo),
        "indexed": total_indexed,
        "people": total_people,
        "details": detalhes,
        "errors": errors,
    }


def _ingest_only(items: List[Dict[str, Any]], nif: str) -> Dict[str, Any]:
    """Indexa as publicações sem mexer no PessoasIQ."""
    from api.elasticsearch_client import index_societario_items

    docs = societario.normalize_items(items)
    result = index_societario_items(docs, replace_for_nif=nif)
    result["received"] = len(items)
    return result


# ---------------------------------------------------------------------------
# Trabalhos (recolha massiva em segundo plano)
# ---------------------------------------------------------------------------

def _prune_jobs() -> None:
    if len(_JOBS) <= _JOBS_KEEP:
        return
    antigos = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""))
    for job in antigos[: len(_JOBS) - _JOBS_KEEP]:
        if job.get("status") == _RUNNING:
            continue
        _JOBS.pop(str(job["job_id"]), None)


def start_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Arranca a recolha massiva em segundo plano e devolve o id do trabalho."""
    with _JOBS_LOCK:
        running = [job for job in _JOBS.values() if job.get("status") == _RUNNING]
        if running:
            return {
                "job_id": running[0]["job_id"],
                "status": _RUNNING,
                "already_running": True,
                "message": "Já existe uma recolha massiva a correr.",
            }
        job: Dict[str, Any] = {
            "job_id": uuid.uuid4().hex[:12],
            "status": _RUNNING,
            "started_at": _now(),
            "finished_at": None,
            "payload": payload,
            "progress": {
                "phase": "a escolher os alvos",
                "entities_done": 0,
                "entities_total": 0,
                "publications": 0,
                "files": 0,
                "current": None,
            },
            "result": None,
            "error": None,
        }
        _JOBS[job["job_id"]] = job
        _prune_jobs()

    thread = threading.Thread(target=_run_job, args=(job,), name="societario-recolha", daemon=True)
    thread.start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    """Corre a recolha massiva, garantindo que o trabalho nunca fica «a correr».

    As importações e o arranque também estão dentro de um `try`: uma falha aí
    deixava o trabalho pendurado em «a escolher os alvos» sem qualquer erro.
    """
    try:
        _run_job_inner(job)
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Recolha massiva falhou antes do ciclo de recolha")
        job["status"] = "error"
        job["finished_at"] = _now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["progress"]["phase"] = "erro"
        job["progress"]["current"] = None


def _run_job_inner(job: Dict[str, Any]) -> None:
    """Corre a recolha massiva e vai atualizando o progresso do trabalho."""
    from collectors.publicacoes_mj import CaptchaRequiredError, RateLimitedError
    from collectors.publicacoes_mj_captcha import PublicacoesMjCaptchaClient

    payload = job["payload"]
    progress = job["progress"]
    with_people = bool(payload.get("ingest", True))
    pausa_rate_limit = max(0.0, float(payload.get("rate_limit_pause") or 90.0))
    tentativas_rate_limit = max(0, min(int(payload.get("rate_limit_retries") or 2), 10))
    try:
        alvos = targets(
            ano_ini=payload.get("ano_ini"),
            ano_fim=payload.get("ano_fim"),
            papel=payload.get("papel") or "ambos",
            q=payload.get("q"),
            nifs=payload.get("nifs"),
            min_contracts=int(payload.get("min_contracts") or 1),
            min_value=payload.get("min_value"),
            exclude_collected=bool(payload.get("exclude_collected", True)),
            limit=int(payload.get("max_entities") or 50),
        )
        if alvos.get("error"):
            raise RuntimeError(alvos["error"])
        entidades = alvos.get("items") or []
        progress["entities_total"] = len(entidades)
        progress["phase"] = "a recolher"

        if not entidades:
            job["status"] = "done"
            job["finished_at"] = _now()
            job["result"] = {"entities": 0, "publications": 0, "files": 0, "errors": [], "message": "Nenhuma entidade elegível."}
            return

        client = PublicacoesMjCaptchaClient(
            api_key=payload.get("api_key"),
            min_interval=float(payload.get("min_interval") or 1.0),
            recaptcha_timeout=int(payload.get("recaptcha_timeout") or 180),
            proxy=payload.get("proxy"),
            debug=bool(payload.get("debug")),
        )

        janelas: List[Any] = [(None, None)]
        if payload.get("data_ini") and payload.get("data_fim"):
            janelas = societario._janelas(str(payload["data_ini"]), str(payload["data_fim"]), societario.MAX_DATE_RANGE_DAYS)

        erros: List[Dict[str, Any]] = []
        detalhes: List[Dict[str, Any]] = []
        publicacoes = 0
        ficheiros = 0
        limitados = 0

        def recolher_entidade(nif: str, nome: Any) -> Any:
            """Recolhe uma entidade, com pausa e nova tentativa se o portal limitar.

            Devolve ``(items, erro, limitado)``: o rate-limit é uma condição
            externa e transitória, por isso não se mistura com os erros de dados.
            """
            for tentativa in range(tentativas_rate_limit + 1):
                recolhidas: List[Dict[str, Any]] = []
                bloqueado = False
                for janela in janelas:
                    criteria: Dict[str, Any] = {"nif": nif, "tipo": str(payload.get("tipo") or "0")}
                    if janela[0] and janela[1]:
                        criteria["data_ini"] = janela[0]
                        criteria["data_fim"] = janela[1]
                    display = dict(criteria)
                    display["data_ini"] = societario._as_portal_date(display.get("data_ini"))
                    display["data_fim"] = societario._as_portal_date(display.get("data_fim"))
                    try:
                        publications = client.collect(
                            with_details=bool(payload.get("with_details", True)),
                            max_pages=int(payload.get("max_pages") or 50),
                            **display,
                        )
                    except RateLimitedError as exc:
                        bloqueado = True
                        if tentativa >= tentativas_rate_limit:
                            return [], f"rate-limit: {exc}", True
                        break
                    except CaptchaRequiredError as exc:
                        return [], f"captcha: {exc}", False
                    except Exception as exc:  # noqa: BLE001 - uma entidade má não trava o lote
                        logger.exception("Falha na recolha de %s", nif)
                        return [], str(exc), False
                    recolhidas.extend(pub.to_dict() for pub in publications)
                if not bloqueado:
                    return recolhidas, None, False
                progress["phase"] = f"portal a limitar pedidos — pausa de {int(pausa_rate_limit)}s"
                logger.warning(
                    "Portal do MJ a limitar %s; pausa de %.0fs antes da tentativa %s/%s",
                    nif,
                    pausa_rate_limit,
                    tentativa + 2,
                    tentativas_rate_limit + 1,
                )
                time.sleep(pausa_rate_limit)
                progress["phase"] = "a recolher"
            return [], "rate-limit persistente", True

        for entidade in entidades:
            nif = str(entidade.get("nif") or "").strip()
            nome = entidade.get("name")
            if not nif:
                continue
            progress["current"] = {"nif": nif, "name": nome}
            items, erro, limitado = recolher_entidade(nif, nome)
            if erro:
                if limitado:
                    limitados += 1
                erros.append({"nif": nif, "name": nome, "error": erro})
                if limitado and payload.get("stop_on_captcha"):
                    progress["phase"] = "interrompido (portal a limitar)"
                    break
            if items:
                try:
                    written = write_export(nif, nome, items, criteria=alvos.get("filters"))
                    ficheiros += 1
                    if with_people:
                        societario.ingest(items, replace_for_nif=nif)
                    detalhes.append({**written, "name": nome, "ingested": with_people})
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Falha a gravar o JSON de %s", nif)
                    erros.append({"nif": nif, "name": nome, "error": f"gravação: {exc}"})
                publicacoes += len(items)
                progress["publications"] = publicacoes
                progress["files"] = ficheiros
            progress["entities_done"] += 1

        job["status"] = "done"
        job["finished_at"] = _now()
        job["result"] = {
            "entities": len(entidades),
            "entities_with_publications": len(detalhes),
            "publications": publicacoes,
            "files": ficheiros,
            "rate_limited": limitados,
            "ingested": with_people,
            "export_dir": str(export_dir()),
            "details": detalhes,
            "errors": erros,
        }
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Recolha massiva falhou")
        job["status"] = "error"
        job["finished_at"] = _now()
        job["error"] = str(exc)
    finally:
        progress["phase"] = "concluído" if job["status"] == "done" else "erro"
        progress["current"] = None


def list_jobs() -> Dict[str, Any]:
    """Estado dos trabalhos de recolha (mais recentes primeiro)."""
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""), reverse=True)
        return {"total": len(jobs), "items": [dict(job) for job in jobs]}


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Estado de um trabalho de recolha."""
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id))
        return dict(job) if job else None


def meta() -> Dict[str, Any]:
    """Metadados do módulo de recolha massiva."""
    manifest = list_exports()
    return {
        "module": "societario-recolha",
        "export_dir": manifest["dir"],
        "export_dir_env": EXPORT_DIR_ENV,
        "index": "finance_publicacoes_mj",
        "files": manifest["total"],
        "publications_exported": manifest["publications"],
        "notes": (
            "Um ficheiro JSON por entidade (`societario-<NIF>.json`), com as publicações de atos "
            "societários recolhidas do portal do Ministério da Justiça (reCAPTCHA por 2captcha). "
            "A indexação em `finance_publicacoes_mj` é uma passagem separada e idempotente."
        ),
    }
