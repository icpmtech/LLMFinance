"""Recolha massiva de empresas a partir de diretórios web (ex.: Iberinform.pt).

Este módulo especializa o scraper genérico do IQ OS para recolha de **fichas
empresariais** com dois objetivos:

1. correr recolhas por **distrito/concelho** e exportar um JSON organizado;
2. oferecer um ponto de entrada de API/UI para arrancar recolhas em lote,
   consultar o seu progresso e injetar os resultados no EmpresasIQ.

A recolha propriamente dita é feita pelo `api.scraper_service` (Scrapling);
este serviço apenas:

- constrói a fonte a partir do template `iberinform-diretorio`;
- gere um job em memória (id, progresso, resultado);
- exporta o resultado para `EXPORT_DIR` organizado por distrito/concelho;
- expõe funções síncronas que as rotas e os scripts de raiz consomem.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from api import scraper_service
from api.scraper_templates import build_source

logger = logging.getLogger(__name__)

#: Pasta base das exportações (pode ser sobrescrita por env var).
EXPORT_DIR_ENV = "EMPRESAS_RECOLHA_EXPORT_DIR"
_DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "scraper" / "exports" / "empresas"

#: Jobs em memória (id → estado). Mantêm-se os últimos `_JOBS_KEEP`.
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 20
_RUNNING = "running"


def export_dir() -> Path:
    """Pasta das exportações, criada se não existir."""
    raw = (os.environ.get(EXPORT_DIR_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else _DEFAULT_EXPORT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sem_acentos(text: str) -> str:
    decomposto = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposto if not unicodedata.combining(ch))


def _slugify(text: str) -> str:
    """Converte um nome num slug seguro para ficheiros/pastas.

    Remove os acentos antes de reduzir a `[a-z0-9_]`, porque os URLs do
    Iberinform usam o nome sem diacríticos («Évora» → `evora`, não `vora`).
    """
    s = _sem_acentos(text).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_") or "sem_nome"


def _slug_url(text: str) -> str:
    """Slug **como o site o escreve**: minúsculas, sem acentos e com hífenes.

    Não usar `_slugify` nos URLs: os hífenes fazem parte do endereço
    (`castelo-branco`, `viana-do-castelo`); trocá-los por `_` dá 404.
    """
    s = _sem_acentos(text).lower().strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _build_source(
    distrito: str,
    concelho: str,
    start_page: int = 1,
    max_pages: int = 1,
    detail: bool = True,
    delay: float = 1.0,
) -> Dict[str, Any]:
    """Constroi uma fonte Iberinform para o distrito/concelho pedido."""
    url = f"https://www.iberinform.pt/diretorio/{_slug_url(distrito)}/{_slug_url(concelho)}/pagina/{max(1, int(start_page))}"
    src = build_source(
        "iberinform-diretorio",
        overrides={
            "url": url,
            "name": f"Empresas {distrito.title()}/{concelho.title()}",
            "enabled": True,
            "tags": ["empresas", "iberinform", "diretorio", distrito.lower(), concelho.lower()],
        },
    )
    # Id estável por distrito/concelho (sem acentos): repetir a recolha atualiza a
    # mesma fonte em vez de acumular fontes novas, e o `item_id` fica legível.
    src["id"] = f"empresas-{_slugify(distrito)}-{_slugify(concelho)}"
    src["pagination"] = {
        **src.get("pagination", {}),
        "max_pages": max(1, int(max_pages)),
    }
    src["detail"] = {
        **src.get("detail", {}),
        "enabled": bool(detail),
        "max_items": 0,
        "delay": float(delay),
        "max_chars": 20000,
    }
    return src


def _export_path(distrito: str, concelho: str, start_page: int, max_pages: int) -> Path:
    base = export_dir() / _slugify(distrito) / _slugify(concelho)
    base.mkdir(parents=True, exist_ok=True)
    end_page = max(1, int(start_page)) + max(1, int(max_pages)) - 1
    return base / f"pagina_{int(start_page)}_a_{end_page}.json"


def _read_jsonl_items(run_id: str, source_id: str) -> List[Dict[str, Any]]:
    path = scraper_service._items_path(run_id, source_id)
    items: List[Dict[str, Any]] = []
    if not path.exists():
        return items
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def run_sync(
    distrito: str,
    concelho: str,
    start_page: int = 1,
    max_pages: int = 1,
    *,
    detail: bool = True,
    delay: float = 1.0,
    keep_source: bool = True,
    ingest: bool = False,
    all_pages: bool = False,
) -> Dict[str, Any]:
    """Recolha síncrona por distrito/concelho. Usado pelos scripts e pela UI.

    Com `all_pages=True`, `max_pages` passa a ser apenas o **teto de segurança** e
    a recolha segue a paginação do site até não haver página seguinte; o ficheiro
    exportado fica com o número de páginas realmente recolhidas.

    Devolve um dicionário com metadados, caminho do ficheiro exportado e a
    lista de itens recolhidos.
    """
    distrito = distrito.strip()
    concelho = concelho.strip()
    source = _build_source(distrito, concelho, start_page, max_pages, detail=detail, delay=delay)
    saved = scraper_service.upsert_source(source)
    source_id = saved["id"]

    try:
        meta = scraper_service.execute_run_sync(source_id, trigger="manual")
    except Exception as exc:
        logger.exception("Recolha de empresas falhou para %s/%s", distrito, concelho)
        return {"ok": False, "error": str(exc), "distrito": distrito, "concelho": concelho}

    run_id = meta.get("run_id")
    items = _read_jsonl_items(run_id, source_id)
    # Páginas realmente recolhidas: com `all_pages` o nome do ficheiro deve
    # refletir o que existe, não o teto pedido.
    pages_real = int(meta.get("pages") or 0)
    pages_efetivas = pages_real if (all_pages and pages_real > 0) else max(1, int(max_pages))
    out_file = _export_path(distrito, concelho, start_page, pages_efetivas)
    payload = {
        "distrito": distrito,
        "concelho": concelho,
        "start_page": int(start_page),
        "max_pages": int(max_pages),
        "pages": pages_real,
        "all_pages": bool(all_pages),
        "run_id": run_id,
        "source_id": source_id,
        "collected_at": _now(),
        "meta": meta,
        "items": items,
    }
    tmp = out_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_file)

    # A indexação é feita automaticamente por _execute_run; não precisamos de
    # chamar nada extra. O campo `ingest` fica reservado para futuras
    # integrações com o índice `finance_empresas`.

    if not keep_source:
        try:
            scraper_service.delete_source(source_id, purge_items=False)
        except Exception as exc:
            logger.warning("Não foi possível apagar a fonte temporária %s: %s", source_id, exc)

    return {
        "ok": True,
        "distrito": distrito,
        "concelho": concelho,
        "start_page": int(start_page),
        "max_pages": int(max_pages),
        "pages": pages_real,
        "run_id": run_id,
        "source_id": source_id,
        "file": str(out_file),
        "file_rel": str(out_file.relative_to(export_dir())),
        "items_count": len(items),
        "meta": meta,
    }


def start_job(
    distrito: str,
    concelho: str,
    start_page: int = 1,
    max_pages: int = 1,
    *,
    detail: bool = True,
    delay: float = 1.0,
    keep_source: bool = True,
    ingest: bool = False,
    all_pages: bool = False,
) -> Dict[str, Any]:
    """Arranca uma recolha em segundo plano e devolve o id do job."""
    job_id = f"emp-{uuid.uuid4().hex[:10]}"

    def _run() -> None:
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = _RUNNING
            _JOBS[job_id]["started_at"] = _now()
        try:
            result = run_sync(
                distrito=distrito,
                concelho=concelho,
                start_page=start_page,
                max_pages=max_pages,
                detail=detail,
                delay=delay,
                keep_source=keep_source,
                ingest=ingest,
                all_pages=all_pages,
            )
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "done" if result.get("ok") else "error"
                _JOBS[job_id]["result"] = result
                _JOBS[job_id]["finished_at"] = _now()
                if not result.get("ok"):
                    _JOBS[job_id]["error"] = result.get("error")
        except Exception as exc:
            logger.exception("Job %s falhou", job_id)
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "error"
                _JOBS[job_id]["error"] = str(exc)
                _JOBS[job_id]["finished_at"] = _now()
        finally:
            with _JOBS_LOCK:
                while len(_JOBS) > _JOBS_KEEP:
                    _JOBS.pop(next(iter(_JOBS)), None)

    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "payload": {
                "distrito": distrito,
                "concelho": concelho,
                "start_page": start_page,
                "max_pages": max_pages,
                "detail": detail,
                "delay": delay,
                "ingest": ingest,
                "all_pages": all_pages,
            },
            "result": None,
            "error": None,
        }
    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running"}


def get_job(job_id: str) -> Dict[str, Any]:
    """Devolve o estado de um job."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return {"error": "Job não encontrado.", "job_id": job_id}
    return dict(job)


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """Lista os jobs mais recentes (mais recente primeiro)."""
    with _JOBS_LOCK:
        jobs = list(_JOBS.values())
    jobs.sort(key=lambda j: j.get("started_at") or "", reverse=True)
    return jobs[:max(1, int(limit))]


def list_exports(
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Lista os ficheiros JSON exportados, opcionalmente filtrados."""
    base = export_dir()
    files: List[Dict[str, Any]] = []
    pattern = "**/*.json"
    if distrito:
        base = base / _slugify(distrito)
        if concelho:
            base = base / _slugify(concelho)
    for path in base.glob(pattern):
        if path.name.endswith(".tmp"):
            continue
        rel = path.relative_to(export_dir())
        parts = rel.parts
        files.append({
            "distrito": parts[0] if len(parts) > 1 else None,
            "concelho": parts[1] if len(parts) > 2 else None,
            "file": str(rel),
            "path": str(path),
            "bytes": path.stat().st_size,
            "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        })
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return {"total": len(files), "files": files[:max(1, int(limit))], "export_dir": str(export_dir())}


def read_export(path: str) -> Dict[str, Any]:
    """Lê um ficheiro de exportação (caminho relativo ou absoluto)."""
    p = Path(path)
    if not p.is_absolute():
        p = export_dir() / p
    if not p.exists():
        return {"error": f"Ficheiro não encontrado: {path}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Ficheiro ilegível: {exc}", "path": str(p)}
    data.setdefault("path", str(p))
    return data


#: Seletor do bloco com a ficha da empresa nas páginas de detalhe do Iberinform.
DETAIL_SELECTOR = "section.section-company-data"
#: Seletor alternativo usado por versões mais antigas/mobile da mesma página.
DETAIL_SELECTOR_FALLBACK = "div#detalleEmpresa"


def preview_item(url: str) -> Dict[str, Any]:
    """Recolhe o detalhe de uma empresa individual a partir do URL.

    Exemplo: `https://www.iberinform.pt/empresa/24050518/...`

    Usa exatamente a mesma extração da recolha em lote (o bloco
    `section.section-company-data`, com o texto achatado), para que a
    pré-visualização seja igual ao que fica gravado no JSON.
    """
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "URL vazio."}
    options = {"impersonate": "chrome", "timeout": 30}
    stats: Dict[str, int] = {}
    try:
        with scraper_service._open_session("http", options) as session:
            page = scraper_service._session_fetch(session, "http", url, options)
    except Exception as exc:
        logger.warning("Detalhe de %s falhou: %s", url, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "url": url}
    if page is None:
        return {"ok": False, "error": "A página não devolveu conteúdo.", "url": url}

    text = ""
    for selector in (DETAIL_SELECTOR, DETAIL_SELECTOR_FALLBACK):
        try:
            text = scraper_service._longest_node_text(page, selector, "css")[:20000]
        except Exception as exc:
            logger.debug("Seletor %s falhou em %s: %s", selector, url, exc)
            text = ""
        if text:
            break

    nif = ""
    match = re.search(r"/empresa/(\d+)", url)
    if match:
        nif = match.group(1)

    item: Dict[str, Any] = {
        "url": url,
        "nif": nif,
        "title": "",
        "summary": "",
        "text": text,
        "detail": bool(text),
        "scraped_at": _now(),
    }
    if text:
        # O texto vem achatado («Dados Gerais de NOME Data de última consulta …»):
        # o nome da empresa é o que fica entre «Dados Gerais de» e o rótulo seguinte.
        match_nome = re.search(r"Dados Gerais de (.+?)\s+(?:Data de|Raz[ãa]o Social|Denomina)", text)
        nome = match_nome.group(1).strip() if match_nome else text[:160]
        item["title"] = nome
        item["summary"] = nome
    stats["detail_count"] = 1 if text else 0
    return {
        "ok": bool(text),
        "pages": 1,
        "total": 1,
        "items": [item],
        "detail_count": stats["detail_count"],
        "detail_errors": 0 if text else 1,
        "duplicates": 0,
    }


#: Teto de segurança de páginas por concelho quando se recolhe um distrito todo.
DISTRICT_MAX_PAGES = 200


def _distrito_url(distrito: str) -> str:
    return f"https://www.iberinform.pt/diretorio/{_slug_url(distrito)}"


#: TTL do catálogo de distritos/concelhos lido do site (segundos).
CATALOG_TTL = 3600
_CATALOG: Dict[str, Any] = {"at": 0.0, "data": None}
_CATALOG_LOCK = threading.Lock()


def _fetch_html(url: str):
    """Lê uma página do diretório (sessão HTTP curta, como a recolha)."""
    options = {"impersonate": "chrome", "timeout": 30}
    with scraper_service._open_session("http", options) as session:
        return scraper_service._session_fetch(session, "http", url, options)


#: Ligações do diretório que **não** são distritos (ramos paralelos do site).
DIRETORIO_NAO_DISTRITO = {"diretorio-cnae", "diretorio", "empresas"}

#: Pausa entre pedidos do catálogo (evita throttling ao varrer o país).
CATALOG_PAUSA = 1.0


def _ligacoes_diretoria(page: Any, prefixo: str) -> List[Dict[str, Any]]:
    """Ligações `/diretorio/<prefixo>/<slug>` da página, com o texto visível.

    Devolve `{"slug", "nome", "empresas"}` sem repetições e por ordem de
    aparição. O nome visível («Évora», «Montemor-o-Novo») é melhor para a UI do
    que o slug e o site acrescenta o total de empresas entre parênteses
    («Empresas de Évora (7.453)»), que se aproveita para planear a recolha.
    """
    base = f"/diretorio/{prefixo}" if prefixo else "/diretorio"
    padrao = re.compile(rf"^{re.escape(base)}/([a-z0-9\-]+)/?$", re.I)
    contagem = re.compile(r"\(([\d\.\s\u00a0]+)\)\s*$")
    vistos: Dict[str, Dict[str, Any]] = {}
    for node in page.css("a"):
        href = str(node.attrib.get("href") or "").strip()
        match = padrao.match(href)
        if not match:
            continue
        slug = match.group(1).lower()
        if slug in vistos:
            continue
        texto = (node.get_all_text(strip=True) or "").strip()
        empresas: Optional[int] = None
        achado = contagem.search(texto)
        if achado:
            digitos = re.sub(r"[^\d]", "", achado.group(1))
            empresas = int(digitos) if digitos else None
            texto = contagem.sub("", texto).strip()
        # «Empresas de Évora» → «Évora»
        nome = re.sub(r"^\s*empresas?\s+de\s+", "", texto, flags=re.I).strip() or slug.replace("-", " ").title()
        vistos[slug] = {"slug": slug, "nome": nome, "empresas": empresas}
    return list(vistos.values())


def distritos_do_site() -> List[Dict[str, Any]]:
    """Todos os distritos com diretório no Iberinform."""
    page = _fetch_html("https://www.iberinform.pt/diretorio")
    if page is None:
        raise RuntimeError("Sem resposta de https://www.iberinform.pt/diretorio")
    return [d for d in _ligacoes_diretoria(page, "") if d["slug"] not in DIRETORIO_NAO_DISTRITO]


def concelhos_do_site(distrito: str) -> List[str]:
    """Concelhos de um distrito, lidos da página do próprio diretório.

    Evita listas escritas à mão (e respetivos erros de slug): o site publica
    ligações `/diretorio/<distrito>/<concelho>` na página do distrito.
    """
    return [item["slug"] for item in concelhos_com_nome_do_site(distrito)]


def concelhos_com_nome_do_site(distrito: str) -> List[Dict[str, Any]]:
    """Concelhos de um distrito, com slug, nome visível e n.º de empresas."""
    distrito_slug = _slugify(distrito)
    url = _distrito_url(distrito)
    page = _fetch_html(url)
    if page is None:
        raise RuntimeError(f"Sem resposta de {url}")
    # A própria página do distrito é paginada (`/diretorio/<d>/pagina/N`); essas
    # ligações não são concelhos.
    return [c for c in _ligacoes_diretoria(page, distrito_slug) if c["slug"] != "pagina"]


def catalogo(forcar: bool = False) -> Dict[str, Any]:
    """Distritos **e** concelhos disponíveis no diretório (com cache de 1 hora).

    Uma passagem completa são ~1 pedido por distrito, pelo que fica em cache: a
    UI pode pedir o catálogo à vontade sem martelar o site. Cada distrito é
    pedido com uma pausa e, se vier sem concelhos (throttling), repete uma vez.
    """
    with _CATALOG_LOCK:
        if not forcar and _CATALOG["data"] and (time.time() - float(_CATALOG["at"])) < CATALOG_TTL:
            return _CATALOG["data"]

    distritos = distritos_do_site()
    saida: List[Dict[str, Any]] = []
    for posicao, distrito in enumerate(distritos):
        if posicao:
            time.sleep(CATALOG_PAUSA)
        item: Dict[str, Any] = {
            "slug": distrito["slug"],
            "nome": distrito["nome"],
            "empresas": distrito.get("empresas"),
            "concelhos": [],
        }
        for tentativa in range(2):
            try:
                item["concelhos"] = concelhos_com_nome_do_site(distrito["slug"])
            except Exception as exc:
                logger.warning("Concelhos de %s falharam: %s", distrito["slug"], exc)
                item["error"] = str(exc)
                break
            if item["concelhos"]:
                item.pop("error", None)
                break
            logger.info("Distrito %s veio sem concelhos; nova tentativa", distrito["slug"])
            time.sleep(2.0)
        original = next((d for d in distritos if d["slug"] == distrito["slug"]), None)
        item["empresas"] = sum(c.get("empresas") or 0 for c in item["concelhos"]) or (original or {}).get("empresas")
        saida.append(item)

    total_concelhos = sum(len(d["concelhos"]) for d in saida)
    total_empresas = sum(c.get("empresas") or 0 for d in saida for c in d["concelhos"])
    data = {
        "source": "iberinform.pt",
        "updated_at": _now(),
        "ttl": CATALOG_TTL,
        "distritos": saida,
        "total_distritos": len(saida),
        "total_concelhos": total_concelhos,
        "total_empresas": total_empresas,
        "sem_concelhos": [d["slug"] for d in saida if not d["concelhos"]],
    }
    with _CATALOG_LOCK:
        _CATALOG["data"] = data
        _CATALOG["at"] = time.time()
    return data


def _manifest_path(distrito: str) -> Path:
    base = export_dir() / _slugify(distrito)
    base.mkdir(parents=True, exist_ok=True)
    return base / "_manifest.json"


def read_manifest(distrito: str) -> Dict[str, Any]:
    """Manifesto da recolha de um distrito (estado por concelho)."""
    path = _manifest_path(distrito)
    if not path.exists():
        return {"distrito": distrito, "concelhos": {}, "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Manifesto ilegível em %s: %s", path, exc)
        return {"distrito": distrito, "concelhos": {}, "updated_at": None}
    data.setdefault("distrito", distrito)
    data.setdefault("concelhos", {})
    return data


def _write_manifest(distrito: str, manifest: Dict[str, Any]) -> None:
    manifest["distrito"] = distrito
    manifest["updated_at"] = _now()
    path = _manifest_path(distrito)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_district_sync(
    distrito: str,
    *,
    start_page: int = 1,
    max_pages: int = DISTRICT_MAX_PAGES,
    detail: bool = True,
    delay: float = 0.5,
    ingest: bool = False,
    skip_done: bool = True,
    concelhos: Optional[List[str]] = None,
    on_progress: Optional[Any] = None,
    paralelo: int = 1,
) -> Dict[str, Any]:
    """Recolhe **todos os concelhos de um distrito**, todas as páginas de cada um.

    Cada concelho fica num JSON próprio (`<distrito>/<concelho>/pagina_X_a_Y.json`)
    e o manifesto `<distrito>/_manifest.json` guarda o estado, para que uma
    segunda passagem com `skip_done=True` continue só o que falta.

    `paralelo > 1` recolhe vários concelhos ao mesmo tempo (cada um é uma fonte
    independente, com a sua sessão HTTP e o seu ficheiro de execução).

    `on_progress(evento)` é chamado a cada mudança de estado (`inicio`,
    `concelho_inicio`, `concelho_fim`, `fim`), para o trabalho em segundo plano
    poder reportar progresso.
    """
    distrito = distrito.strip()
    nomes = [c.strip().lower() for c in (concelhos or []) if c.strip()] or concelhos_do_site(distrito)
    manifest = read_manifest(distrito)
    estado: Dict[str, Any] = manifest.setdefault("concelhos", {})

    def reportar(evento: Dict[str, Any]) -> None:
        if on_progress:
            try:
                on_progress(evento)
            except Exception:  # a UI nunca deve quebrar a recolha
                logger.debug("on_progress falhou", exc_info=True)

    reportar({"tipo": "inicio", "distrito": distrito, "concelhos": nomes})
    resultados: List[Optional[Dict[str, Any]]] = [None] * len(nomes)

    def _recolher(indice: int, nome: str) -> Optional[Dict[str, Any]]:
        anterior = estado.get(nome) or {}
        if skip_done and anterior.get("ok"):
            resumo = {**anterior, "concelho": nome, "saltado": True}
            resultados[indice] = resumo
            reportar(
                {
                    "tipo": "concelho_fim",
                    "concelho": nome,
                    "indice": indice,
                    "total": len(nomes),
                    "saltado": True,
                    "resultado": resumo,
                }
            )
            return resumo

        reportar({"tipo": "concelho_inicio", "concelho": nome, "indice": indice, "total": len(nomes)})
        res = run_sync(
            distrito=distrito,
            concelho=nome,
            start_page=start_page,
            max_pages=max_pages,
            detail=detail,
            delay=delay,
            ingest=ingest,
            all_pages=True,
        )
        resumo = {
            "concelho": nome,
            "ok": bool(res.get("ok")),
            "items_count": int(res.get("items_count") or 0),
            "pages": int(res.get("pages") or 0),
            "file": res.get("file_rel") or res.get("file"),
            "run_id": res.get("run_id"),
            "collected_at": _now(),
        }
        if not res.get("ok"):
            resumo["error"] = res.get("error")
        resultados[indice] = resumo
        with _JOBS_LOCK:  # o manifesto é partilhado: escrita serializada
            estado[nome] = resumo
            _write_manifest(distrito, manifest)
        reportar({"tipo": "concelho_fim", "concelho": nome, "indice": indice, "total": len(nomes), "resultado": resumo})
        return resumo

    trabalhadores = max(1, min(int(paralelo or 1), 6, len(nomes) or 1))
    if trabalhadores == 1:
        for indice, nome in enumerate(nomes):
            _recolher(indice, nome)
    else:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=trabalhadores) as pool:
            futuros = {pool.submit(_recolher, i, n): n for i, n in enumerate(nomes)}
            for futuro in concurrent.futures.as_completed(futuros):
                nome = futuros[futuro]
                try:
                    futuro.result()
                except Exception as exc:  # nunca perder os restantes concelhos
                    logger.exception("Concelho %s falhou de forma inesperada", nome)
                    indice = nomes.index(nome)
                    resultados[indice] = {"concelho": nome, "ok": False, "items_count": 0, "error": str(exc)}

    resultados_finais = [r for r in resultados if r]
    total_itens = sum(int(r.get("items_count") or 0) for r in resultados_finais)
    manifest["total_items"] = sum(int(v.get("items_count") or 0) for v in estado.values())
    manifest["concelhos_ok"] = sum(1 for v in estado.values() if v.get("ok"))
    _write_manifest(distrito, manifest)

    falhados = [r["concelho"] for r in resultados_finais if not r.get("ok")]
    saida = {
        "ok": not falhados,
        "distrito": distrito,
        "concelhos": resultados_finais,
        "total_concelhos": len(nomes),
        "concelhos_ok": manifest["concelhos_ok"],
        "total_items": total_itens,
        "falhados": falhados,
        "manifest": str(_manifest_path(distrito)),
    }
    reportar({"tipo": "fim", "distrito": distrito, "resultado": saida})
    return saida


def start_district_job(
    distrito: str,
    *,
    start_page: int = 1,
    max_pages: int = DISTRICT_MAX_PAGES,
    detail: bool = True,
    delay: float = 0.5,
    ingest: bool = False,
    skip_done: bool = True,
    paralelo: int = 1,
) -> Dict[str, Any]:
    """Arranca em segundo plano a recolha de **todos os concelhos de um distrito**."""
    job_id = f"dist-{uuid.uuid4().hex[:10]}"

    def _progresso(evento: Dict[str, Any]) -> None:
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
            if not job:
                return
            job["progress"] = evento
            if evento.get("tipo") == "concelho_inicio":
                job["concelho_atual"] = evento.get("concelho")
                job["concelhos_feitos"] = int(job.get("concelhos_feitos") or 0)
            elif evento.get("tipo") == "concelho_fim":
                feito = job.setdefault("progresso_concelhos", {})
                feito[evento["concelho"]] = evento.get("resultado") or {}
                job["concelhos_feitos"] = len(feito)

    def _run() -> None:
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = _RUNNING
            _JOBS[job_id]["started_at"] = _now()
        try:
            resultado = run_district_sync(
                distrito,
                start_page=start_page,
                max_pages=max_pages,
                detail=detail,
                delay=delay,
                ingest=ingest,
                skip_done=skip_done,
                paralelo=paralelo,
                on_progress=_progresso,
            )
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "done" if resultado.get("ok") else "error"
                _JOBS[job_id]["result"] = resultado
                _JOBS[job_id]["concelhos"] = resultado.get("concelhos")
                _JOBS[job_id]["finished_at"] = _now()
                if not resultado.get("ok"):
                    _JOBS[job_id]["error"] = f"Concelhos com falha: {', '.join(resultado.get('falhados') or [])}"
        except Exception as exc:
            logger.exception("Recolha do distrito %s falhou", distrito)
            with _JOBS_LOCK:
                _JOBS[job_id]["status"] = "error"
                _JOBS[job_id]["error"] = str(exc)
                _JOBS[job_id]["finished_at"] = _now()
        finally:
            with _JOBS_LOCK:
                while len(_JOBS) > _JOBS_KEEP:
                    _JOBS.pop(next(iter(_JOBS)), None)

    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "kind": "distrito",
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "payload": {
                "distrito": distrito,
                "start_page": start_page,
                "max_pages": max_pages,
                "detail": detail,
                "delay": delay,
                "ingest": ingest,
                "skip_done": skip_done,
                "paralelo": paralelo,
            },
            "progress": None,
            "concelho_atual": None,
            "concelhos_feitos": 0,
            "progresso_concelhos": {},
            "concelhos": None,
            "result": None,
            "error": None,
        }
    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id, "status": "running", "paralelo": paralelo}


def districts_from_exports() -> List[str]:
    """Devolve a lista de distritos que têm exportações."""
    base = export_dir()
    if not base.exists():
        return []
    return sorted({p.name for p in base.iterdir() if p.is_dir()})


def councils_from_exports(distrito: str) -> List[str]:
    """Devolve a lista de concelhos de um distrito com exportações."""
    base = export_dir() / _slugify(distrito)
    if not base.exists():
        return []
    return sorted({p.name for p in base.iterdir() if p.is_dir()})
