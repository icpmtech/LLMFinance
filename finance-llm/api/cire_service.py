"""Serviço do módulo CIRE — publicidade do PER, PEAP, PEVE e da insolvência.

Liga o coletor (`collectors/citius_cire.py`) ao disco (`data/cire/`) e ao
Elasticsearch (`finance_cire`), no mesmo desenho dos outros módulos:

1. **Recolha** — `collect()` pesquisa o portal do CITIUS, percorre a lista de
   resultados e grava tudo em **JSON** (`data/cire/runs/<run_id>.json`) com um
   resumo ao lado (`<run_id>.meta.json`). Nada é indexado neste passo.
2. **Importação** — `ingest_run()` lê o JSON gravado e indexa no Elasticsearch
   (idempotente: o `_id` é o `pub_id`, derivado da referência + processo + data).

A separação é deliberada: a recolha pode ser repetida/inspecionada sem tocar no
índice, e a importação pode ser refeita a partir do ficheiro (por exemplo depois
de um erro de rede ou de uma alteração ao parser).

O intervalo de datas do portal é livre, mas cada página traz apenas **10
documentos** — para um mês inteiro podem ser centenas de páginas. Por isso a
recolha aceita `max_pages`, `max_items` e `window_days` (divide o intervalo em
janelas, aplicando o limite de páginas a cada uma).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from collectors.citius_cire import (
    DIAS_OPCOES,
    GRUPOS_ACTOS,
    MIN_REQUEST_INTERVAL,
    PAGE,
    PAGE_SIZE,
    CireClient,
    CireError,
)

logger = logging.getLogger(__name__)

# Raiz dos ficheiros de recolha (JSON), ao lado das outras fontes da solução.
ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "cire" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

MAX_WINDOW_DAYS = 366
DEFAULT_WINDOW_DAYS = 31

# Cache das opções do formulário (tribunais e atos), que o portal serve em ~1s.
_OPTIONS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_OPTIONS_TTL = 3600.0


# --------------------------------------------------------------- metadados
def meta() -> Dict[str, Any]:
    """Metadados do módulo (para a UI e para clientes da API)."""
    return {
        "module": "cire",
        "source": "citius.mj.pt",
        "source_label": "Publicidade do PER, PEAP, PEVE e da insolvência (CITIUS / Ministério da Justiça)",
        "source_url": PAGE,
        "index": "finance_cire",
        "storage": str(RUNS_DIR),
        "page_size": PAGE_SIZE,
        "captcha_required": False,
        "max_window_days": MAX_WINDOW_DAYS,
        "default_window_days": DEFAULT_WINDOW_DAYS,
        "min_request_interval": MIN_REQUEST_INTERVAL,
        "dias": [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()],
        "grupos_actos": [{"value": k, "label": v} for k, v in GRUPOS_ACTOS.items()],
        "notes": (
            "Porta de entrada: a lista de resultados da pesquisa do portal. Cada página traz 10 "
            "documentos e a recolha avança página a página (1 pedido por página). Os ficheiros "
            "ficam em `data/cire/runs/` (JSON) e só depois são importados para `finance_cire`."
        ),
    }


def form_options(force: bool = False) -> Dict[str, Any]:
    """Opções do formulário do portal (tribunais, grupos de atos e atos).

    Vêm do próprio portal (os valores dos tribunais são cifrados), por isso são
    guardadas em cache durante uma hora.
    """
    import time

    now = time.time()
    if not force and _OPTIONS_CACHE["data"] and now - _OPTIONS_CACHE["at"] < _OPTIONS_TTL:
        return _OPTIONS_CACHE["data"]

    try:
        with CireClient(min_interval=0.5) as client:
            client.fetch_form()
            data = {
                "tribunais": client.tribunais(),
                "actos": client.actos(),
                "grupos_actos": [{"value": k, "label": v} for k, v in GRUPOS_ACTOS.items()],
                "dias": [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()],
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível obter as opções do CIRE: %s", exc)
        return {"error": str(exc), "tribunais": [], "actos": [],
                "grupos_actos": [{"value": k, "label": v} for k, v in GRUPOS_ACTOS.items()],
                "dias": [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()]}

    _OPTIONS_CACHE["at"] = now
    _OPTIONS_CACHE["data"] = data
    return data


# --------------------------------------------------------------- datas
def normalize_date(value: Optional[str]) -> Optional[str]:
    """Aceita ``AAAA-MM-DD`` e ``DD/MM/AAAA`` e devolve ISO 8601."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def _windows(desde: Optional[str], ate: Optional[str], window_days: Optional[int]) -> List[Tuple[Optional[str], Optional[str]]]:
    """Divide o intervalo em janelas de ``window_days`` dias (mais recente primeiro)."""
    if not desde or not ate or not window_days or window_days <= 0:
        return [(desde, ate)]
    try:
        start = date.fromisoformat(normalize_date(desde) or "")
        end = date.fromisoformat(normalize_date(ate) or "")
    except ValueError:
        return [(desde, ate)]
    if end < start:
        return [(desde, ate)]
    janelas: List[Tuple[Optional[str], Optional[str]]] = []
    cursor = end
    while cursor >= start:
        ini = max(start, cursor - timedelta(days=window_days - 1))
        janelas.append((ini.isoformat(), cursor.isoformat()))
        cursor = ini - timedelta(days=1)
    return janelas


# --------------------------------------------------------------- ficheiros
def run_path(run_id: str) -> Path:
    """Caminho do JSON de uma recolha."""
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
    return RUNS_DIR / f"{safe}.json"


def run_meta_path(run_id: str) -> Path:
    """Caminho do resumo (``.meta.json``) de uma recolha."""
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
    return RUNS_DIR / f"{safe}.meta.json"


def save_run(payload: Dict[str, Any], meta_info: Dict[str, Any]) -> Dict[str, str]:
    """Grava a recolha em JSON (itens) e o respetivo resumo.

    A escrita é atómica (ficheiro temporário + ``replace``) para não deixar
    ficheiros truncados se o processo for interrompido a meio.
    """
    run_id = payload["run_id"]
    path = run_path(run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

    meta_path = run_meta_path(run_id)
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_meta.replace(meta_path)
    return {"run_id": run_id, "path": str(path), "meta_path": str(meta_path)}


def load_run(run_id: str) -> Dict[str, Any]:
    """Lê o JSON de uma recolha (itens + critérios)."""
    path = run_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"Recolha «{run_id}» não encontrada em {RUNS_DIR}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_meta(run_id: str) -> Dict[str, Any]:
    """Lê o resumo de uma recolha."""
    meta_path = run_meta_path(run_id)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """Recolhas gravadas em disco (mais recentes primeiro)."""
    metas: List[Dict[str, Any]] = []
    for meta_path in RUNS_DIR.glob("*.meta.json"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        payload.setdefault("run_id", meta_path.name.removesuffix(".meta.json"))
        metas.append(payload)
    metas.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return metas[: max(1, limit)]


def delete_run(run_id: str) -> Dict[str, Any]:
    """Apaga os ficheiros de uma recolha (JSON e resumo)."""
    removed: List[str] = []
    for path in (run_path(run_id), run_meta_path(run_id)):
        if path.exists():
            path.unlink()
            removed.append(path.name)
    return {"run_id": run_id, "removed": removed}


def latest_run_id() -> Optional[str]:
    """Identificador da recolha mais recente (ou ``None``)."""
    runs = list_runs(1)
    return runs[0].get("run_id") if runs else None


def processed_windows(limit: int = 500) -> List[Dict[str, Any]]:
    """Janelas (``desde``, ``ate``) já recolhidas com sucesso, a partir dos resumos em disco.

    Serve para **não repetir dias já processados**: uma recolha do mesmo intervalo
    só corre outra vez se o utilizador pedir explicitamente (``force``).
    """
    janelas: List[Dict[str, Any]] = []
    vistos: set[tuple] = set()
    for meta_info in list_runs(limit):
        run_id = meta_info.get("run_id")
        if meta_info.get("errors") and not meta_info.get("collected"):
            continue
        for janela in meta_info.get("windows") or []:
            desde, ate = janela.get("desde"), janela.get("ate")
            if not desde or not ate or janela.get("error"):
                continue
            chave = (desde, ate)
            if chave in vistos:
                continue
            vistos.add(chave)
            janelas.append(
                {
                    "desde": desde,
                    "ate": ate,
                    "run_id": run_id,
                    "collected": janela.get("collected") or 0,
                    "total": janela.get("total") or 0,
                    "finished_at": meta_info.get("finished_at") or meta_info.get("created_at"),
                }
            )
    janelas.sort(key=lambda item: (item.get("ate") or "", item.get("desde") or ""), reverse=True)
    return janelas


def coverage() -> Dict[str, Any]:
    """Dias/janelas já recolhidos (para a UI avisar antes de repetir a recolha)."""
    janelas = processed_windows()
    return {
        "windows": janelas,
        "total": len(janelas),
        "days": sorted({j["ate"] for j in janelas if j.get("ate")}, reverse=True),
    }


# --------------------------------------------------------------- recolha
def collect(
    *,
    desde: Optional[str] = None,
    ate: Optional[str] = None,
    dias: Optional[str] = None,
    nif: Optional[str] = None,
    nome: Optional[str] = None,
    numero_processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    grupo_actos: Optional[str] = None,
    acto: Optional[str] = None,
    max_pages: int = 20,
    max_items: Optional[int] = None,
    window_days: Optional[int] = DEFAULT_WINDOW_DAYS,
    min_interval: float = MIN_REQUEST_INTERVAL,
    proxy: Optional[str] = None,
    run_id: Optional[str] = None,
    force: bool = False,
    split_runs: bool = False,
    ingest_each: bool = False,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Recolhe publicações do CIRE e grava-as em JSON (sem tocar no Elasticsearch).

    Devolve ``{"run_id", "payload", "meta"}``: o ``payload`` leva os itens e os
    critérios, o ``meta`` o resumo (totais, páginas, janelas e tempos).

    Com ``split_runs`` cada janela de datas é gravada como uma **recolha própria**
    (JSON + resumo com ``run_id`` derivado do principal) e ``ingest_each`` importa-a
    logo para o Elasticsearch. É o modo indicado para períodos longos: mantém a
    memória constante, deixa reimportar só o que interessa e mostra progresso por
    janela (sem esperar por um JSON gigante no fim).
    """
    desde = normalize_date(desde)
    ate = normalize_date(ate)
    if bool(desde) != bool(ate):
        raise ValueError("Indique as duas datas (início e fim) ou nenhuma.")
    if desde and ate and date.fromisoformat(ate) < date.fromisoformat(desde):
        raise ValueError("A data final não pode ser anterior à inicial.")
    if nome and nif:
        raise ValueError("Escolha pesquisa por NIF/NIPC ou por designação, não ambas.")
    if dias and dias not in DIAS_OPCOES:
        raise ValueError("Atalho de dias inválido (use 15, 30 ou todos).")
    if grupo_actos and str(grupo_actos) not in GRUPOS_ACTOS:
        raise ValueError("Grupo de atos inválido (use 20, 24 ou 25).")

    run_id = run_id or _new_run_id(desde, ate, nif, nome)
    janelas = _windows(desde, ate, window_days if desde and ate else None)
    started = datetime.now(timezone.utc)

    # Dias já processados: sem `force`, as janelas já recolhidas são ignoradas
    # (e o motivo fica em `warnings`, para a UI avisar quem pediu a recolha).
    processadas = {
        (janela["desde"], janela["ate"]): janela for janela in processed_windows()
    }
    warnings: List[str] = []
    ignoradas: List[Dict[str, Any]] = []
    if not force and processadas:
        for janela in list(janelas):
            anterior = processadas.get((janela[0], janela[1]))
            if not anterior:
                continue
            janelas.remove(janela)
            ignoradas.append({**anterior, "motivo": "já processada"})
            warnings.append(
                f"Janela {janela[0]} → {janela[1]} já foi processada "
                f"({anterior.get('collected', 0)} documentos em {anterior.get('run_id')}) — ignorada."
            )

    criterios = {
        "desde": desde,
        "ate": ate,
        "dias": dias,
        "nif": nif,
        "nome": nome,
        "numero_processo": numero_processo,
        "tribunal": tribunal,
        "grupo_actos": str(grupo_actos) if grupo_actos else None,
        "acto": acto,
        "max_pages": max_pages,
        "max_items": max_items,
        "window_days": window_days,
        "force": force,
    }

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    janelas_info: List[Dict[str, Any]] = []
    total_declarado = 0
    paginas = 0
    erros: List[str] = []
    parado = False
    recolhas: List[str] = []
    indexados = 0
    ignorados_index = 0
    # Contadores do progresso (atualizados a cada página, dentro das janelas).
    progresso: Dict[str, Any] = {"collected": 0, "pages": 0}

    with CireClient(min_interval=min_interval, proxy=proxy) as client:
        for janela_desde, janela_ate in janelas:
            if stop and stop():
                parado = True
                break
            try:
                recolhidos, resumo = client.collect(
                    desde=janela_desde,
                    ate=janela_ate,
                    dias=dias if not (janela_desde and janela_ate) else None,
                    nif=nif,
                    nome=nome,
                    numero_processo=numero_processo,
                    tribunal=tribunal,
                    grupo_actos=grupo_actos,
                    acto=acto,
                    max_pages=max_pages,
                    max_items=max_items,
                    stop=stop,
                    on_page=lambda page, new, _d=janela_desde, _a=janela_ate: _report_page(
                        on_progress, progresso, page, new, _d, _a
                    ),
                )
                total_declarado += resumo.get("total", 0)
                paginas += resumo.get("pages", 0)
                novos: List[Dict[str, Any]] = []
                for pub in recolhidos:
                    doc = pub.to_dict()
                    if doc["pub_id"] in seen:
                        continue
                    seen.add(doc["pub_id"])
                    novos.append(doc)

                info_janela: Dict[str, Any] = {
                    "desde": janela_desde,
                    "ate": janela_ate,
                    "total": resumo.get("total", 0),
                    "pages": resumo.get("pages", 0),
                    "collected": len(novos),
                }
                n_novos = len(novos)

                if split_runs:
                    sub_id = _window_run_id(run_id, janela_desde, janela_ate)
                    if novos:
                        sub_payload = {
                            "run_id": sub_id,
                            "source": "citius_cire",
                            "source_url": PAGE,
                            "criteria": {**criterios, "janela": {"desde": janela_desde, "ate": janela_ate},
                                         "parent_run_id": run_id},
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                            "count": len(novos),
                            "items": novos,
                        }
                        sub_meta: Dict[str, Any] = {
                            "run_id": sub_id,
                            "parent_run_id": run_id,
                            "source": "citius_cire",
                            "criteria": criterios,
                            "windows": [info_janela],
                            "collected": len(novos),
                            "declared_total": info_janela["total"],
                            "pages": info_janela["pages"],
                            "page_size": PAGE_SIZE,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "index": "finance_cire",
                            "indexed": 0,
                        }
                        if persist:
                            paths = save_run(sub_payload, sub_meta)
                            info_janela["file"] = paths["path"]
                        recolhas.append(sub_id)
                        if ingest_each:
                            ing = ingest_run(sub_id)
                            indexados += int(ing.get("indexed_count") or 0)
                            ignorados_index += int(ing.get("skipped_existing") or 0)
                            info_janela["indexed"] = ing.get("indexed_count")
                        del novos
                else:
                    items.extend(novos)

                janelas_info.append(info_janela)
                if on_progress:
                    on_progress(
                        {
                            "stage": "window",
                            "window": {"desde": janela_desde, "ate": janela_ate},
                            "window_index": len(janelas_info),
                            "window_total": len(janelas),
                            "collected": n_novos if split_runs else len(items),
                            "total_collected": progresso["collected"],
                            "pages": paginas,
                            "runs": len(recolhas),
                            "indexed": indexados,
                            "file": info_janela.get("file"),
                        }
                    )
            except (CireError, ValueError) as exc:
                logger.warning("Janela %s–%s falhou: %s", janela_desde, janela_ate, exc)
                erros.append(f"{janela_desde}–{janela_ate}: {exc}")
                janelas_info.append({"desde": janela_desde, "ate": janela_ate, "error": str(exc)})

            if max_items and len(items) >= max_items:
                items = items[:max_items]
                break

    finished = datetime.now(timezone.utc)
    payload = {
        "run_id": run_id,
        "source": "citius_cire",
        "source_url": PAGE,
        "criteria": criterios,
        "collected_at": finished.isoformat(),
        "count": len(items),
        "items": items,
    }
    meta_info = {
        "run_id": run_id,
        "source": "citius_cire",
        "criteria": criterios,
        "windows": janelas_info,
        "collected": len(items) if not split_runs else sum(w.get("collected") or 0 for w in janelas_info),
        "declared_total": total_declarado,
        "pages": paginas,
        "page_size": PAGE_SIZE,
        "errors": erros,
        "warnings": warnings,
        "skipped_windows": ignoradas,
        "stopped": parado,
        "created_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 1),
        "index": "finance_cire",
        "indexed": indexados,
        "skipped_existing": ignorados_index,
        "split_runs": split_runs,
        "runs": recolhas,
        "file": str(run_path(run_id)),
    }
    if persist:
        if split_runs or not items:
            # Recolha dividida (ou sem itens): guarda-se só o resumo da operação.
            save_run_meta(meta_info)
            meta_info["meta_file"] = str(run_meta_path(run_id))
        else:
            paths = save_run(payload, meta_info)
            meta_info["file"] = paths["path"]
            meta_info["meta_file"] = paths["meta_path"]

    if on_progress:
        on_progress(
            {
                "stage": "collected",
                "collected": meta_info["collected"],
                "pages": paginas,
                "runs": len(recolhas),
                "indexed": indexados,
                "warnings": warnings,
                "skipped_windows": len(ignoradas),
            }
        )

    return {"run_id": run_id, "payload": payload, "meta": meta_info}


def _window_run_id(parent: str, desde: Optional[str], ate: Optional[str]) -> str:
    """Identificador da recolha de uma janela (``<parent>-<desde>_<ate>``)."""
    sufixo = f"{desde or 'inicio'}_{ate or 'fim'}"
    sufixo = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in sufixo)
    return f"{parent}-{sufixo}"


def save_run_meta(meta_info: Dict[str, Any]) -> str:
    """Grava apenas o resumo (``.meta.json``) de uma recolha."""
    meta_path = run_meta_path(str(meta_info["run_id"]))
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(meta_path)
    return str(meta_path)


def _new_run_id(
    desde: Optional[str], ate: Optional[str], nif: Optional[str], nome: Optional[str]
) -> str:
    """Identificador da recolha: ``cire-<data>-<critério>-<aleatório>``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    alvo = nif or (nome[:20] if nome else None) or (f"{desde}_{ate}" if desde else "todos")
    alvo = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(alvo))
    return f"cire-{stamp}-{alvo}-{uuid.uuid4().hex[:4]}"


def _report_page(
    on_progress: Optional[Callable[[Dict[str, Any]], None]],
    progresso: Dict[str, Any],
    page: Any,
    new: Any,
    desde: Optional[str],
    ate: Optional[str],
) -> None:
    """Relata o progresso da recolha (chamado pelo coletor a cada página)."""
    progresso["pages"] += 1
    progresso["collected"] += len(new)
    if not on_progress:
        return
    on_progress(
        {
            "stage": "collecting",
            "window": {"desde": desde, "ate": ate},
            "page": getattr(page, "page", None),
            "declared_total": getattr(page, "total", 0),
            "collected": progresso["collected"],
            "pages": progresso["pages"],
            "last_batch": len(new),
        }
    )


# --------------------------------------------------------------- importação
def ingest_run(
    run_id: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    mark_meta: bool = True,
    update_existing: bool = False,
) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada (ou a lista de itens dada).

    Sem ``run_id`` nem ``items``, importa a recolha mais recente em disco. Os
    documentos **já existentes no índice são ignorados** (``update_existing=True``
    força a reescrita), pelo que reimportar a mesma recolha não faz nada.
    """
    from api.elasticsearch_client import index_cire_items, search_cire

    payload: Dict[str, Any] = {}
    if items is None:
        run_id = run_id or latest_run_id()
        if not run_id:
            raise FileNotFoundError("Não há recolhas em data/cire/runs para importar.")
        payload = load_run(run_id)
        items = payload.get("items", [])
        run_id = payload.get("run_id", run_id)

    if not items:
        return {"run_id": run_id, "indexed_count": 0, "total": 0, "error": "A recolha não tem itens."}

    result = index_cire_items(items, run_id=run_id, skip_existing=not update_existing)
    result["run_id"] = run_id
    result["total"] = len(items)

    if mark_meta and run_id:
        meta_info = load_run_meta(run_id)
        if meta_info:
            meta_info["indexed"] = result.get("indexed_count", 0)
            meta_info["skipped_existing"] = result.get("skipped_existing", 0)
            meta_info["indexed_at"] = datetime.now(timezone.utc).isoformat()
            meta_path = run_meta_path(run_id)
            meta_path.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")

    # Contagem no índice (confirmação para a UI).
    try:
        estado = search_cire(size=1)
        result["index_total"] = estado.get("total")
    except Exception:  # noqa: BLE001
        pass
    return result


# --------------------------------------------------------------- leitura
def search(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa publicações indexadas do CIRE."""
    from api.elasticsearch_client import search_cire

    return search_cire(**kwargs)


def status() -> Dict[str, Any]:
    """Volumetria do índice do CIRE."""
    from api.elasticsearch_client import cire_status

    return cire_status()


def interveniente(nif: str, size: int = 100, from_: int = 0) -> Dict[str, Any]:
    """Publicações em que um NIF/NIPC é interveniente (qualquer papel)."""
    from api.elasticsearch_client import cire_interveniente as _cire_interveniente

    res = _cire_interveniente(nif, size=size, from_=from_)
    return {**res, "nif": nif}


def runs_with_index_counts(limit: int = 50) -> List[Dict[str, Any]]:
    """Recolhas em disco, anotadas com o número de documentos no Elasticsearch."""
    from api.elasticsearch_client import cire_runs_summary

    metas = list_runs(limit)
    counts = cire_runs_summary([m["run_id"] for m in metas if m.get("run_id")])
    for meta_info in metas:
        meta_info["index_count"] = counts.get(meta_info.get("run_id"), 0)
    return metas
