"""Serviço do módulo «Citação e Notificação Edital» (CITIUS / Ministério da Justiça).

Liga o coletor (`collectors/citius_citacoes.py`) ao disco (`data/citacoes/`) e ao
Elasticsearch (`finance_citacoes_edital`), no mesmo desenho dos restantes módulos:

1. **Recolha** — `collect()` pesquisa o portal do CITIUS pelo **nome do
   interveniente** (o único critério desta consulta), percorre a lista de
   resultados e grava tudo em **JSON** (`data/citacoes/runs/<run_id>.json`) com um
   resumo ao lado (`<run_id>.meta.json`). Nada é indexado neste passo.
2. **Importação** — `ingest_run()` lê o JSON gravado e indexa no Elasticsearch
   (idempotente: o `_id` é o `pub_id`, derivado da referência + processo + data + ato).

O portal devolve os éditos **por data descendente**, pelo que a recolha aceita
`meses` («últimos N meses», por omissão **6**) e **para sozinha** ao passar esse
limite: não vale a pena percorrer anos de éditos antigos para os descartar.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from collectors.citius_citacoes import (
    DIAS_OPCOES,
    MAX_TEXT_CHARS,
    MIN_REQUEST_INTERVAL,
    PAGE,
    PAGE_SIZE,
    CitacoesEditalClient,
    CitacoesError,
    analyze_documento,
    extract_pdf_text,
    total_pages,
)

logger = logging.getLogger(__name__)

# Raiz dos ficheiros de recolha (JSON), ao lado das outras fontes da solução.
ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "citacoes" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

INDEX_NAME = "finance_citacoes_edital"
SOURCE = "citius_citacoes"
SOURCE_LABEL = "Citação e Notificação Edital (CITIUS / Ministério da Justiça)"

#: Meses de histórico recolhidos por omissão («últimos 6 meses»).
DEFAULT_MONTHS = 6
MAX_MONTHS = 120

#: Documentos (PDF) extraídos por recolha, por omissão. Cada documento é um
#: pedido ao portal, logo este teto controla a duração da recolha.
DEFAULT_MAX_DOCUMENTOS = 200

# Cache das opções do formulário (serviços/tribunais), que o portal serve em ~1 s.
_OPTIONS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
_OPTIONS_TTL = 3600.0


# --------------------------------------------------------------- metadados
def meta() -> Dict[str, Any]:
    """Metadados do módulo (para a UI e para clientes da API)."""
    return {
        "module": "citacoes",
        "source": "citius.mj.pt",
        "source_label": SOURCE_LABEL,
        "source_url": PAGE,
        "index": INDEX_NAME,
        "storage": str(RUNS_DIR),
        "page_size": PAGE_SIZE,
        "captcha_required": False,
        "nome_required": True,
        "default_months": DEFAULT_MONTHS,
        "max_months": MAX_MONTHS,
        "min_request_interval": MIN_REQUEST_INTERVAL,
        "dias": [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()],
        "extrair_documentos": True,
        "max_documentos": DEFAULT_MAX_DOCUMENTOS,
        "max_text_chars": MAX_TEXT_CHARS,
        "notas": (
            "Consulta pública do CITIUS com as citações e notificações editais (aquelas em que o "
            "citando não foi encontrado). A pesquisa é **pelo nome do interveniente** (o portal não "
            "aceita NIF/NIPC nem intervalo de datas) e, opcionalmente, por tribunal/serviço. Cada "
            "página traz 10 éditos e os resultados vêm por data descendente, pelo que a recolha "
            "«últimos N meses» para sozinha ao passar esse limite. O **PDF de cada édito é "
            "descarregado e analisado** na mesma sessão (texto integral, modelo, valor da execução, "
            "prazo e NIF dos intervenientes). Os ficheiros ficam em `data/citacoes/runs/` (JSON) e só "
            "depois são importados para `finance_citacoes_edital`."
        ),
    }


def form_options(force: bool = False) -> Dict[str, Any]:
    """Opções do formulário do portal (serviços/tribunais e atalhos de dias)."""
    import time

    now = time.time()
    if not force and _OPTIONS_CACHE["data"] and now - _OPTIONS_CACHE["at"] < _OPTIONS_TTL:
        return _OPTIONS_CACHE["data"]

    dias = [{"value": k, "label": v} for k, v in DIAS_OPCOES.items()]
    try:
        with CitacoesEditalClient(min_interval=0.5) as client:
            client.fetch_form()
            data = {"tribunais": client.tribunais(), "dias": dias}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível obter as opções das citações editais: %s", exc)
        return {"error": str(exc), "tribunais": [], "dias": dias}

    _OPTIONS_CACHE["at"] = now
    _OPTIONS_CACHE["data"] = data
    return data


# --------------------------------------------------------------- datas
def cutoff_from_months(meses: Optional[int]) -> Optional[str]:
    """Data de corte (ISO 8601) dos últimos ``meses`` meses (``None`` = sem corte)."""
    if not meses or meses <= 0:
        return None
    hoje = date.today()
    mes = hoje.month - int(meses)
    ano = hoje.year + (mes - 1) // 12
    mes = (mes - 1) % 12 + 1
    dia = min(hoje.day, 28)
    return date(ano, mes, dia).isoformat()


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
    """Grava a recolha em JSON (itens) e o respetivo resumo (escrita atómica)."""
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


def save_run_meta(meta_info: Dict[str, Any]) -> str:
    """Grava apenas o resumo (``.meta.json``) de uma recolha."""
    meta_path = run_meta_path(str(meta_info["run_id"]))
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(meta_path)
    return str(meta_path)


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


def delete_run(run_id: str, drop_index: bool = False) -> Dict[str, Any]:
    """Apaga os ficheiros de uma recolha (JSON e resumo) e, se pedido, o índice."""
    removed: List[str] = []
    for path in (run_path(run_id), run_meta_path(run_id)):
        if path.exists():
            path.unlink()
            removed.append(path.name)
    resultado: Dict[str, Any] = {"run_id": run_id, "removed": removed}
    if drop_index:
        from api.elasticsearch_client import delete_citacoes_run

        resultado["index"] = delete_citacoes_run(run_id)
    return resultado


def latest_run_id() -> Optional[str]:
    """Identificador da recolha mais recente (ou ``None``)."""
    runs = list_runs(1)
    return runs[0].get("run_id") if runs else None


def _new_run_id(nome: Optional[str]) -> str:
    """Identificador da recolha: ``citacoes-<data>-<nome>-<aleatório>``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    alvo = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(nome or "todos"))
    return f"citacoes-{stamp}-{alvo[:30]}-{uuid.uuid4().hex[:4]}"


# --------------------------------------------------------------- recolha
def collect(
    *,
    nome: str,
    tribunal: Optional[str] = None,
    dias: Optional[str] = None,
    meses: Optional[int] = DEFAULT_MONTHS,
    max_pages: int = 200,
    max_items: Optional[int] = None,
    extrair_documentos: bool = True,
    max_documentos: int = DEFAULT_MAX_DOCUMENTOS,
    max_text_chars: int = MAX_TEXT_CHARS,
    min_interval: float = MIN_REQUEST_INTERVAL,
    proxy: Optional[str] = None,
    run_id: Optional[str] = None,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Recolhe éditos de citação/notificação e grava-os em JSON (sem tocar no Elasticsearch).

    Com ``extrair_documentos`` (por omissão **ligado**) o PDF de cada édito é
descarregado e o seu texto extraído e analisado logo a seguir à lista — na
    **mesma sessão**, porque o token do documento está ligado a ela (uma ligação
    antiga devolve a página «Erro»). Ficam no documento o texto integral, o
    modelo, o valor da execução, o prazo e os **NIF dos intervenientes** (que a
    lista do portal não publica).

    Devolve ``{"run_id", "payload", "meta"}``: o ``payload`` leva os itens e os
    critérios, o ``meta`` o resumo (totais, páginas, documentos extraídos, tempos
    e o corte aplicado).
    """
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Indique o nome do interveniente a pesquisar.")
    if dias and dias not in DIAS_OPCOES:
        raise ValueError("Atalho de dias inválido (use 15, 30 ou todos).")
    if meses is not None and (meses < 0 or meses > MAX_MONTHS):
        raise ValueError(f"«meses» tem de estar entre 0 e {MAX_MONTHS}.")

    desde = cutoff_from_months(meses)
    run_id = run_id or _new_run_id(nome)
    started = datetime.now(timezone.utc)

    criterios = {
        "nome": nome,
        "tribunal": tribunal,
        "dias": dias or "todos",
        "meses": meses,
        "desde": desde,
        "max_pages": max_pages,
        "max_items": max_items,
        "extrair_documentos": bool(extrair_documentos),
        "max_documentos": max_documentos,
    }

    itens: List[Dict[str, Any]] = []
    seen: set[str] = set()
    erros: List[str] = []
    parado = False
    paginas = 0
    total_declarado = 0
    antigos = 0
    docs_resumo: Dict[str, Any] = {}

    def _report(page: Any, novos: List[Any]) -> None:
        nonlocal paginas
        paginas = max(paginas, int(getattr(page, "page", 0) or 0))
        if on_progress:
            on_progress(
                {
                    "stage": "collecting",
                    "page": getattr(page, "page", None),
                    "pages": getattr(page, "pages_total", None),
                    "declared_total": getattr(page, "total", 0),
                    "collected": len(itens) + len(novos),
                    "last_batch": len(novos),
                    "desde": desde,
                }
            )

    def _report_doc(indice: int, total: int, edito: Any, ok: bool, erro: Optional[str]) -> None:
        if on_progress:
            on_progress(
                {
                    "stage": "documentos",
                    "documento": indice,
                    "documentos": total,
                    "referencia": getattr(edito, "referencia", None),
                    "titulo": (getattr(edito, "documento", None) or {}).get("documento_titulo"),
                    "ok": ok,
                    "erro": erro,
                }
            )

    try:
        with CitacoesEditalClient(min_interval=min_interval, proxy=proxy) as client:
            # O corte por data faz-se aqui (o portal não aceita intervalos livres):
            # a lista vem por data descendente, pelo que basta parar ao passar o limite.
            items, resumo = client.collect(
                nome=nome,
                tribunal=tribunal,
                dias=dias or "todos",
                desde=desde,
                max_pages=max_pages,
                max_items=max_items,
                on_page=_report,
                stop=stop,
            )
            total_declarado = resumo.get("total", 0)
            paginas = resumo.get("pages", paginas)
            antigos = resumo.get("oldest_skipped", 0)

            if extrair_documentos and items:
                docs_resumo = client.extrair_documentos(
                    items,
                    max_documentos=max_documentos,
                    max_text_chars=max_text_chars,
                    on_document=_report_doc,
                    stop=stop,
                )

            for edito in items:
                doc = edito.to_dict()
                if doc["pub_id"] in seen:
                    continue
                seen.add(doc["pub_id"])
                itens.append(doc)
            parado = bool(stop and stop())
    except (CitacoesError, ValueError) as exc:
        logger.warning("Recolha de citações editais «%s» falhou: %s", nome, exc)
        erros.append(str(exc))

    finished = datetime.now(timezone.utc)
    payload = {
        "run_id": run_id,
        "source": SOURCE,
        "source_url": PAGE,
        "criteria": criterios,
        "collected_at": finished.isoformat(),
        "count": len(itens),
        "items": itens,
    }
    meta_info = {
        "run_id": run_id,
        "source": SOURCE,
        "criteria": criterios,
        "collected": len(itens),
        "declared_total": total_declarado,
        "declared_pages": total_pages("", total_declarado),
        "pages": paginas,
        "page_size": PAGE_SIZE,
        "older_than_cutoff": antigos,
        "documentos": docs_resumo,
        "documentos_extraidos": int(docs_resumo.get("extraidos") or 0),
        "documentos_falhados": int(docs_resumo.get("falhados") or 0),
        "documentos_caracteres": int(docs_resumo.get("caracteres") or 0),
        "errors": erros,
        "stopped": parado,
        "created_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 1),
        "index": INDEX_NAME,
        "indexed": 0,
        "file": str(run_path(run_id)),
    }
    if persist:
        paths = save_run(payload, meta_info)
        meta_info["file"] = paths["path"]
        meta_info["meta_file"] = paths["meta_path"]

    if on_progress:
        on_progress(
            {
                "stage": "collected",
                "collected": meta_info["collected"],
                "declared_total": total_declarado,
                "pages": paginas,
                "errors": erros,
            }
        )

    return {"run_id": run_id, "payload": payload, "meta": meta_info}


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
    from api.elasticsearch_client import index_citacoes_items, search_citacoes

    payload: Dict[str, Any] = {}
    if items is None:
        run_id = run_id or latest_run_id()
        if not run_id:
            raise FileNotFoundError("Não há recolhas em data/citacoes/runs para importar.")
        payload = load_run(run_id)
        items = payload.get("items", [])
        run_id = payload.get("run_id", run_id)

    if not items:
        return {"run_id": run_id, "indexed_count": 0, "total": 0, "error": "A recolha não tem itens."}

    result = index_citacoes_items(items, run_id=run_id, skip_existing=not update_existing)
    result["run_id"] = run_id
    result["total"] = len(items)

    if mark_meta and run_id:
        meta_info = load_run_meta(run_id)
        if meta_info:
            meta_info["indexed"] = result.get("indexed_count", 0)
            meta_info["skipped_existing"] = result.get("skipped_existing", 0)
            meta_info["indexed_at"] = datetime.now(timezone.utc).isoformat()
            run_meta_path(run_id).write_text(
                json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    try:
        estado = search_citacoes(size=1)
        result["index_total"] = estado.get("total")
    except Exception:  # noqa: BLE001
        pass
    return result


# --------------------------------------------------------------- documentos
def _precisa_documento(doc: Dict[str, Any], force: bool) -> bool:
    """Indica se um édito precisa de (nova) extração do PDF."""
    if force:
        return bool(doc.get("has_documento") or doc.get("documento_url"))
    return bool(doc.get("has_documento") or doc.get("documento_url")) and not doc.get("texto")


def extrair_documentos_run(
    run_id: Optional[str] = None,
    *,
    max_documentos: int = DEFAULT_MAX_DOCUMENTOS,
    max_text_chars: int = MAX_TEXT_CHARS,
    force: bool = False,
    min_interval: float = MIN_REQUEST_INTERVAL,
    proxy: Optional[str] = None,
    reindex: bool = True,
    update_existing: bool = True,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Extrai o texto dos PDF de uma recolha já gravada em JSON.

    O token do documento está ligado à **sessão** da pesquisa, pelo que a extração
    volta a fazer a pesquisa no portal (com os mesmos critérios da recolha) para
    obter tokens frescos e casar os éditos pelo ``pub_id``. O texto, a análise e os
    NIF são acrescentados ao JSON da recolha e reenviados ao índice.
    """
    from collectors.citius_citacoes import EditalCitacao

    run_id = run_id or latest_run_id()
    if not run_id:
        raise FileNotFoundError("Não há recolhas em data/citacoes/runs.")

    payload = load_run(run_id)
    meta_info = load_run_meta(run_id)
    criterios = payload.get("criteria") or meta_info.get("criteria") or {}
    nome = (criterios.get("nome") or "").strip()
    if not nome:
        raise ValueError("A recolha não guardou o «nome» do interveniente — não é possível repetir a pesquisa no portal.")

    itens: List[Dict[str, Any]] = payload.get("items") or []
    alvos = [doc for doc in itens if _precisa_documento(doc, force)]
    if not alvos:
        return {
            "run_id": run_id,
            "alvos": 0,
            "extraidos": 0,
            "falhados": 0,
            "mensagem": "Todos os éditos da recolha já têm o texto do documento extraído.",
        }
    alvos = alvos[: max(1, int(max_documentos)) if max_documentos else alvos]
    faltam = {str(doc["pub_id"]) for doc in alvos}
    por_id = {str(doc["pub_id"]): doc for doc in itens}

    desde = criterios.get("desde")
    pedidos = extraidos = falhados = 0
    caracteres = 0
    parado = False

    with CitacoesEditalClient(min_interval=min_interval, proxy=proxy) as client:
        pagina = client.search(
            nome=nome,
            tribunal=criterios.get("tribunal"),
            dias=criterios.get("dias") or "todos",
        )
        while faltam:
            if stop and stop():
                parado = True
                break
            for edito in pagina.items:
                if edito.pub_id not in faltam:
                    continue
                faltam.discard(edito.pub_id)
                if not edito.doc_token:
                    falhados += 1
                    continue
                pedidos += 1
                erro: Optional[str] = None
                try:
                    pdf = client.fetch_documento(edito.doc_token)
                    extraido = extract_pdf_text(pdf, max_chars=max_text_chars)
                    if extraido.get("erro"):
                        erro = str(extraido["erro"])
                    else:
                        edito.texto = extraido.get("texto")
                        edito.documento = {
                            **(edito.documento or {}),
                            **analyze_documento(edito.texto),
                            "documento_paginas": extraido.get("paginas"),
                            "documento_caracteres": extraido.get("caracteres"),
                            "documento_bytes": len(pdf),
                            "documento_extraido_em": datetime.now(timezone.utc).isoformat(),
                        }
                        edito.enriquecer_intervenientes()
                        extraidos += 1
                        caracteres += int(extraido.get("caracteres") or 0)
                except Exception as exc:  # noqa: BLE001
                    erro = str(exc)
                if erro:
                    falhados += 1
                    edito.documento = {**(edito.documento or {}), "documento_erro": erro[:300]}
                # O documento atualizado substitui o que estava gravado.
                por_id[edito.pub_id] = {**por_id[edito.pub_id], **edito.to_dict()}
                if on_progress:
                    on_progress(
                        {
                            "stage": "documentos",
                            "documento": pedidos,
                            "documentos": len(alvos),
                            "referencia": edito.referencia,
                            "titulo": (edito.documento or {}).get("documento_titulo"),
                            "ok": erro is None,
                            "erro": erro,
                            "extraidos": extraidos,
                            "falhados": falhados,
                        }
                    )
            if not faltam or not pagina.has_next:
                break
            if desde and pagina.items and all(
                item.data_publicacao and item.data_publicacao < desde for item in pagina.items
            ):
                # Passou-se o corte da recolha: os éditos que faltam já não vêm.
                break
            pagina = client.next_page()

    if extraidos or force:
        ordem = [str(doc["pub_id"]) for doc in itens]
        payload["items"] = [por_id[pub_id] for pub_id in ordem if pub_id in por_id]
        payload["count"] = len(payload["items"])
        meta_info = {
            **meta_info,
            "documentos_extraidos": int(meta_info.get("documentos_extraidos") or 0) + extraidos,
            "documentos_falhados": int(meta_info.get("documentos_falhados") or 0) + falhados,
            "documentos_caracteres": int(meta_info.get("documentos_caracteres") or 0) + caracteres,
            "documentos_atualizado_em": datetime.now(timezone.utc).isoformat(),
        }
        save_run(payload, meta_info)

    resultado: Dict[str, Any] = {
        "run_id": run_id,
        "alvos": len(alvos),
        "pedidos": pedidos,
        "extraidos": extraidos,
        "falhados": falhados,
        "caracteres": caracteres,
        "por_extrair": len(faltam),
        "parado": parado,
        "indexado": 0,
    }
    if reindex and extraidos:
        ingest = ingest_run(run_id, update_existing=update_existing)
        resultado["indexado"] = ingest.get("indexed_count", 0)
        resultado["index_total"] = ingest.get("index_total")
        resultado["error"] = ingest.get("error")
    return resultado


def texto_documento(pub_id: str) -> Dict[str, Any]:
    """Texto extraído do PDF de um édito (por ``pub_id``)."""
    from api.elasticsearch_client import get_citacao

    doc = get_citacao(pub_id)
    if not doc or doc.get("error"):
        return {"pub_id": pub_id, "error": doc.get("error") if doc else "Édito não encontrado"}
    return {
        "pub_id": pub_id,
        "referencia": doc.get("referencia"),
        "titulo": doc.get("documento_titulo"),
        "assunto": doc.get("documento_assunto"),
        "modelo": doc.get("documento_modelo"),
        "valor": doc.get("documento_valor"),
        "prazo": doc.get("documento_prazo"),
        "nifs": doc.get("documento_nifs") or [],
        "partes": doc.get("documento_partes") or [],
        "paginas": doc.get("documento_paginas"),
        "caracteres": doc.get("documento_caracteres"),
        "extraido_em": doc.get("documento_extraido_em"),
        "erro": doc.get("documento_erro"),
        "texto": doc.get("texto"),
    }


# --------------------------------------------------------------- grafo/mapa
def grafo(**kwargs: Any) -> Dict[str, Any]:
    """Constrói o grafo dos éditos (rede de entidades, tribunais, tipos, tempo)."""
    from api.citacoes_graph import build_citacoes_graph

    return build_citacoes_graph(**kwargs)


def grafo_dimensoes() -> Dict[str, Any]:
    """Dimensões, métricas e receitas disponíveis para o grafo."""
    from api.citacoes_graph import citacoes_graph_dimensions

    return citacoes_graph_dimensions()


def mapa(**kwargs: Any) -> Dict[str, Any]:
    """Constrói os pontos do mapa OpenStreetMap (por sede, comarca ou serviço)."""
    from api.citacoes_map import build_citacoes_map

    return build_citacoes_map(**kwargs)


def mapa_niveis() -> List[Dict[str, str]]:
    """Níveis de agregação do mapa."""
    from api.citacoes_map import mapa_niveis as _niveis

    return _niveis()


# --------------------------------------------------------------- leitura
def search(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa éditos já indexados."""
    from api.elasticsearch_client import search_citacoes as _search

    return _search(**kwargs)


def entidades(**kwargs: Any) -> Dict[str, Any]:
    """Entidades (intervenientes) dos éditos, agregadas por nome.

    Responde a «que entidades aparecem e onde»: pesquisar por nome e filtrar
    (papel, tipo, tribunal, comarca, datas) sem devolver os éditos um a um.
    """
    from api.elasticsearch_client import search_citacoes_entidades

    return search_citacoes_entidades(**kwargs)


def status() -> Dict[str, Any]:
    """Volumetria do índice das citações editais."""
    from api.elasticsearch_client import citacoes_status

    return citacoes_status()


def runs_with_index_counts(limit: int = 50) -> List[Dict[str, Any]]:
    """Recolhas em disco, anotadas com o número de documentos no Elasticsearch."""
    from api.elasticsearch_client import citacoes_runs_summary

    metas = list_runs(limit)
    counts = citacoes_runs_summary([m["run_id"] for m in metas if m.get("run_id")])
    for meta_info in metas:
        meta_info["index_count"] = counts.get(meta_info.get("run_id"), 0)
    return metas
