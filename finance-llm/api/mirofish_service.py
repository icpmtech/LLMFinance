"""Integração com o **MiroFish** (`/mirofish/*`) — previsão por enxame de agentes.

O MiroFish (https://github.com/666ghj/MiroFish) simula um mundo digital a partir
de **material-semente** (relatórios, notícias, fichas) e de um **pedido de
previsão** em linguagem natural: constrói um grafo de conhecimento (Zep), gera
personas, corre a simulação em duas plataformas paralelas e escreve um relatório.

Este módulo liga essa máquina aos **dados do sistema**:

1. **Recolha** — cada fonte (`SOURCES`) transforma dados reais do IQ OS num
   documento-semente em Markdown: ficha de empresa (contratos, sinais, cargos,
   CIRE), tema do *Pesquisa 360*, digest do leitor RSS, documento do Office/dossiê
   guardado, ou o **panorama do sistema** (volumetria + destaques).
2. **Condução** — `run_simulation()` encadeia os passos da API do MiroFish
   (projeto/ontologia → grafo → simulação → personas → execução → relatório) e
   vai registando o progresso num *job* consultável pelo frontend.

O MiroFish expõe uma API Flask em `:5001` (servida ao browser pelo proxy de
incorporação do nginx, `:8893`). O endereço interno lê-se de `MIROFISH_URL`
(por omissão `http://mirofish:5001`, o nome do serviço no compose).

Nota: o backend do MiroFish **recusa arrancar sem `LLM_API_KEY` e
`ZEP_API_KEY`** — sem essas chaves em `.env` não há `GET /health` e a integração
responde `available: false` com a explicação.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:5001"
HTTP_TIMEOUT = float(os.getenv("MIROFISH_HTTP_TIMEOUT", "600"))
POLL_INTERVAL = max(1.0, float(os.getenv("MIROFISH_POLL_INTERVAL", "5")))
STEP_TIMEOUT = float(os.getenv("MIROFISH_STEP_TIMEOUT", "3600"))
MAX_JOBS = 40

#: Estados terminais devolvidos pelo MiroFish (`TaskStatus`, simulações, relatórios).
DONE_STATES = {"completed", "success", "ready", "done", "finished"}
FAILED_STATES = {"failed", "error", "cancelled", "canceled", "stopped", "timeout"}


class MiroFishError(RuntimeError):
    """Erro devolvido (ou não compreendido) pela API do MiroFish."""


# ---------------------------------------------------------------------------
# Ligação ao serviço
# ---------------------------------------------------------------------------
def base_url() -> str:
    """Endereço interno da API do MiroFish (`MIROFISH_URL`)."""
    return (os.getenv("MIROFISH_URL") or DEFAULT_URL).rstrip("/")


def public_url() -> str:
    """Endereço público da UI (para links), quando configurado."""
    return (os.getenv("MIROFISH_PUBLIC_URL") or "").rstrip("/")


def _client(timeout: Optional[float] = None) -> httpx.Client:
    # `Accept-Language: pt` faz o backend do MiroFish responder nas mensagens de
    # progresso/erro em português (ele traz o `locales/pt.json` da nossa imagem).
    return httpx.Client(
        base_url=base_url(),
        timeout=timeout or HTTP_TIMEOUT,
        headers={"Accept-Language": "pt"},
    )


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # pragma: no cover - resposta não-JSON
        return (response.text or "")[:400]


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or body)[:300]
    return str(body)[:300]


def _payload(response: httpx.Response, action: str) -> Dict[str, Any]:
    """Valida o envelope `{success, data, error}` usado pelo MiroFish."""
    body = _json(response)
    if response.status_code >= 400:
        raise MiroFishError(f"{action}: HTTP {response.status_code} — {_error_text(body)}")
    if isinstance(body, dict) and body.get("success") is False:
        raise MiroFishError(f"{action}: {_error_text(body)}")
    data = body.get("data") if isinstance(body, dict) else body
    if isinstance(data, dict):
        return data
    return {"value": data}


def health() -> Dict[str, Any]:
    """Estado do serviço (disponível? qual o endereço? porque falhou?)."""
    try:
        with _client(20) as client:
            response = client.get("/health")
        body = _json(response)
        return {
            "available": response.status_code < 400,
            "base_url": base_url(),
            "status": response.status_code,
            "service": (body or {}).get("service") if isinstance(body, dict) else None,
            "detail": None if response.status_code < 400 else _error_text(body),
        }
    except Exception as exc:  # serviço parado / chaves em falta
        return {
            "available": False,
            "base_url": base_url(),
            "detail": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Passos da API do MiroFish
# ---------------------------------------------------------------------------
def create_project(
    client: httpx.Client,
    *,
    files: Sequence[Tuple[str, str]],
    requirement: str,
    name: str,
    context: str = "",
) -> Dict[str, Any]:
    """`POST /api/graph/ontology/generate` — cria o projeto e a ontologia."""
    payload: Dict[str, Any] = {
        "simulation_requirement": requirement,
        "project_name": name,
    }
    if context:
        payload["additional_context"] = context
    upload = [("files", (filename, content, "text/markdown; charset=utf-8")) for filename, content in files]
    response = client.post("/api/graph/ontology/generate", data=payload, files=upload)
    return _payload(response, "geração da ontologia")


def build_graph(client: httpx.Client, project_id: str) -> Dict[str, Any]:
    """`POST /api/graph/build` — envia o texto para o Zep e constrói o grafo."""
    response = client.post("/api/graph/build", json={"project_id": project_id})
    return _payload(response, "construção do grafo")


def get_task(client: httpx.Client, task_id: str) -> Dict[str, Any]:
    """`GET /api/graph/task/{task_id}` — progresso de uma tarefa assíncrona."""
    response = client.get(f"/api/graph/task/{task_id}")
    return _payload(response, "estado da tarefa")


def create_simulation(client: httpx.Client, project_id: str) -> Dict[str, Any]:
    """`POST /api/simulation/create` — instância de simulação para o projeto."""
    response = client.post("/api/simulation/create", json={"project_id": project_id})
    return _payload(response, "criação da simulação")


def prepare_simulation(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`POST /api/simulation/prepare` — personas e configuração do mundo."""
    response = client.post("/api/simulation/prepare", json={"simulation_id": simulation_id})
    return _payload(response, "preparação do ambiente")


def prepare_status(client: httpx.Client, *, task_id: str = "", simulation_id: str = "") -> Dict[str, Any]:
    """`POST /api/simulation/prepare/status` — progresso da preparação."""
    body = {"task_id": task_id} if task_id else {"simulation_id": simulation_id}
    response = client.post("/api/simulation/prepare/status", json=body)
    return _payload(response, "progresso da preparação")


def start_simulation(
    client: httpx.Client,
    simulation_id: str,
    *,
    max_rounds: Optional[int] = None,
    platform: str = "parallel",
) -> Dict[str, Any]:
    """`POST /api/simulation/start` — arranca a simulação (agentes a interagir)."""
    body: Dict[str, Any] = {"simulation_id": simulation_id, "platform": platform}
    if max_rounds:
        body["max_rounds"] = int(max_rounds)
    response = client.post("/api/simulation/start", json=body)
    return _payload(response, "arranque da simulação")


def run_status(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/run-status` — estado da execução."""
    response = client.get(f"/api/simulation/{simulation_id}/run-status")
    return _payload(response, "estado da execução")


def generate_report(client: httpx.Client, simulation_id: str, *, force: bool = False) -> Dict[str, Any]:
    """`POST /api/report/generate` — pede o relatório da simulação."""
    response = client.post("/api/report/generate", json={"simulation_id": simulation_id, "force_regenerate": force})
    return _payload(response, "geração do relatório")


def report_status(client: httpx.Client, report_id: str) -> Dict[str, Any]:
    """`GET /api/report/generate/status` — progresso do relatório."""
    response = client.get("/api/report/generate/status", params={"report_id": report_id})
    return _payload(response, "progresso do relatório")


def get_report(client: httpx.Client, report_id: str) -> Dict[str, Any]:
    """`GET /api/report/{id}` — relatório gerado."""
    response = client.get(f"/api/report/{report_id}")
    return _payload(response, "relatório")


def list_projects(client: httpx.Client) -> List[Dict[str, Any]]:
    """`GET /api/graph/project/list` — projetos já criados."""
    response = client.get("/api/graph/project/list")
    data = _payload(response, "lista de projetos")
    items = data.get("data") if isinstance(data.get("data"), list) else data.get("value")
    return [item for item in (items or []) if isinstance(item, dict)]


def list_simulations(client: httpx.Client) -> List[Dict[str, Any]]:
    """`GET /api/simulation/list` — simulações já criadas."""
    response = client.get("/api/simulation/list")
    data = _payload(response, "lista de simulações")
    items = data.get("data") if isinstance(data.get("data"), list) else data.get("value")
    return [item for item in (items or []) if isinstance(item, dict)]


def _wait(
    client: httpx.Client,
    fetch: Callable[[], Dict[str, Any]],
    *,
    label: str,
    log: Callable[[str], None],
    timeout: float = STEP_TIMEOUT,
    interval: float = POLL_INTERVAL,
) -> Dict[str, Any]:
    """Espera por um passo assíncrono, registando o progresso no *job*."""
    deadline = time.monotonic() + max(30.0, timeout)
    last = ""
    while True:
        state = fetch()
        status = str(state.get("status") or state.get("runner_status") or "").lower()
        message = str(state.get("message") or state.get("phase") or "").strip()
        progress = state.get("progress")
        if status in FAILED_STATES:
            raise MiroFishError(f"{label}: {state.get('error') or message or status}")
        if status in DONE_STATES:
            if message or progress:
                suffix = f" ({progress}%)" if isinstance(progress, int) else ""
                log(f"{label}: {(message or 'concluído')}{suffix}")
            return state
        info = message or status or "a aguardar"
        if isinstance(progress, int):
            info = f"{info} ({progress}%)"
        if info != last:
            last = info
            log(f"{label}: {info}")
        if time.monotonic() > deadline:
            raise MiroFishError(f"{label}: tempo limite de {int(timeout)}s excedido ({info})")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Recolha de dados do sistema → documento-semente
# ---------------------------------------------------------------------------
def _slug(value: str, fallback: str = "semente") -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:60] or fallback


def _num(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    text = f"{number:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def _clean(text: Any, max_len: int = 400) -> str:
    """Limpa um texto para Markdown: normaliza espaços e corta em max_len."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    if len(cleaned) <= max_len:
        return cleaned
    # Corte inteligente: último espaço antes do limite; senão, corte rígido com "…".
    cut = cleaned.rfind(" ", 0, max_len - 1)
    if cut < max_len // 2:
        cut = max_len - 1
    return cleaned[:cut].rstrip() + "…"


def _euro(value: Any) -> str:
    text = _num(value)
    return f"{text} €" if text != "—" else "—"


def _table(rows: Sequence[Sequence[Any]], header: Sequence[str]) -> str:
    if not rows:
        return "_(sem registos)_\n"
    lines = ["| " + " | ".join(str(item) for item in header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def _bullet(items: Sequence[str], empty: str = "_(nada a assinalar)_") -> str:
    lines = [f"- {item}" for item in items if str(item or "").strip()]
    return "\n".join(lines) + "\n" if lines else f"{empty}\n"


def _es():
    """Cliente Elasticsearch da plataforma (`None` se indisponível)."""
    from api.elasticsearch_client import get_es_client

    return get_es_client()


def _safe_count(es: Any, index: str) -> Optional[int]:
    if es is None:
        return None
    try:
        return int((es.count(index=index) or {}).get("count") or 0)
    except Exception as exc:  # índice ausente não deve quebrar a semente
        logger.debug("mirofish: contagem de %s falhou: %s", index, exc)
        return None


def _safe_search(es: Any, index: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if es is None:
        return None
    try:
        return es.search(index=index, body=body)
    except Exception as exc:
        logger.debug("mirofish: pesquisa em %s falhou: %s", index, exc)
        return None


def _hits(response: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not response:
        return []
    return [hit for hit in ((response.get("hits") or {}).get("hits") or []) if isinstance(hit, dict)]


def _buckets(response: Optional[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    if not response:
        return []
    return [item for item in (((response.get("aggregations") or {}).get(key) or {}).get("buckets") or []) if isinstance(item, dict)]


def _cargos_text(cargos: Sequence[Dict[str, Any]]) -> str:
    """Texto curto dos cargos de uma pessoa (ex.: «Gerente (Sociedade X) desde 2021-03-02»)."""
    parts: List[str] = []
    for cargo in cargos:
        role = str(cargo.get("role") or "cargo")
        org = cargo.get("role_org")
        when = cargo.get("data") or "—"
        parts.append(f"{role} ({org}) desde {when}" if org else f"{role} desde {when}")
    return ", ".join(parts)


# --- 1. Ficha de empresa ----------------------------------------------------
def _markdown_empresa(dossier: Dict[str, Any], *, max_contratos: int = 25) -> str:
    """Markdown de uma ficha de empresa a partir do dossiê do módulo Padrões."""
    if dossier.get("error"):
        raise MiroFishError(f"dossiê da empresa indisponível: {dossier['error']}")
    nome = dossier.get("nome") or dossier.get("nif")
    resumo = dossier.get("resumo") or {}
    contratos = dossier.get("contratos") or []
    partes: List[str] = [
        f"# Ficha de empresa — {nome}",
        "",
        "Documento-semente gerado pelo IQ OS a partir dos dados do sistema "
        "(Portal BASE, CIRE, registo societário e Padrões de Deteção). "
        "Valores em euros; datas em ISO 8601.",
        "",
        "## 1. Identificação",
        "",
        f"- **NIF**: {dossier.get('nif')}",
        f"- **Nome**: {nome}",
        f"- **País**: {dossier.get('pais')}",
        f"- **Contratos no Portal BASE**: {dossier.get('contratos_total') or len(contratos)}",
        f"- **Processos no CIRE (insolvências)**: {dossier.get('insolvencias_total') or len(dossier.get('insolvencias') or [])}",
        f"- **Pessoas ligadas (registo societário)**: {dossier.get('pessoas_total') or 0}",
        "",
        "## 2. Contratos públicos",
        "",
        f"- **Valor total adjudicado**: {_euro(resumo.get('valor_total'))}",
        f"- **Valor mediano**: {_euro(resumo.get('valor_mediano'))}",
        f"- **Desvio mediano face ao preço base**: {_num(resumo.get('desvio_mediano'))}",
        f"- **Taxa de ajuste direto**: {_num((resumo.get('taxa_ajuste_direto') or 0) * 100, 1)} %",
        f"- **Adjudicantes distintos**: {resumo.get('adjudicantes_distintos')}",
        f"- **Taxa de contratos com aditivo**: {_num((resumo.get('taxa_aditivo') or 0) * 100, 1)} %",
        f"- **Anos com contratos**: {', '.join(str(ano) for ano in (resumo.get('anos') or [])) or '—'}",
        "",
    ]
    maiores = sorted(contratos, key=lambda item: item.get("valor") or 0, reverse=True)[:max_contratos]
    partes.append(f"### Maiores contratos ({len(maiores)} de {len(contratos)})")
    partes.append("")
    partes.append(
        _table(
            [
                [
                    contrato.get("ano") or "—",
                    contrato.get("adjudicante") or "—",
                    (contrato.get("objeto") or "—")[:90],
                    _euro(contrato.get("valor")),
                    contrato.get("procedimento") or "—",
                    contrato.get("n_concorrentes") if contrato.get("n_concorrentes") is not None else "—",
                ]
                for contrato in maiores
            ],
            ["Ano", "Adjudicante", "Objeto", "Valor", "Procedimento", "Concorrentes"],
        )
    )
    partes.append("")
    partes.append("## 3. Sinais detetados pelos Padrões de Deteção")
    partes.append("")
    partes.append(_bullet([f"**{sinal.get('padrao')}** — {sinal.get('detalhe')}" for sinal in (dossier.get("sinais") or [])]))
    cargos = dossier.get("cargos_sociais") or []
    if cargos:
        partes.append("## 4. Cargos sociais")
        partes.append("")
        partes.append(
            _bullet(
                [
                    f"{pessoa.get('nome')} — {_cargos_text(pessoa.get('cargos') or [])}"
                    for pessoa in cargos[:15]
                ]
            )
        )
    insolvencias = dossier.get("insolvencias") or []
    if insolvencias:
        partes.append("## 5. Insolvências (CIRE)")
        partes.append("")
        partes.append(
            _table(
                [
                    [item.get("data") or "—", item.get("especie") or "—", item.get("ato") or "—", item.get("tribunal") or "—", item.get("processo") or "—"]
                    for item in insolvencias[:20]
                ],
                ["Data", "Espécie", "Ato", "Tribunal", "Processo"],
            )
        )
    noticias = dossier.get("noticias") or []
    if noticias:
        partes.append("## 6. Notícias")
        partes.append("")
        partes.append(
            _bullet(
                [
                    f"[{item.get('title') or item.get('titulo')}]({item.get('link') or item.get('url') or '#'})"
                    f" — {item.get('published') or item.get('data') or '—'}"
                    for item in noticias[:15]
                ]
            )
        )
    return "\n".join(partes).strip() + "\n"


# --- 2. Tema do Pesquisa 360 ------------------------------------------------
def _markdown_tema(dossier: Dict[str, Any]) -> str:
    """Markdown de um dossiê do *Pesquisa 360* (tem síntese, indicadores e evidências)."""
    from api.search360_store import dossier_markdown

    markdown = dossier_markdown(dossier)
    prefixo = (
        "Documento-semente gerado pelo IQ OS a partir do módulo **Pesquisa 360** "
        "(plataforma + Wikipédia/Wikidata/Banco Mundial/dados.gov/OpenAlex/Crossref/web).\n\n"
    )
    return f"# Tema: {dossier.get('term') or dossier.get('title') or 'sem título'}\n\n{prefixo}{markdown}".strip() + "\n"


# --- 3. Notícias (leitor RSS) ----------------------------------------------
def _markdown_noticias(articles: Sequence[Dict[str, Any]], *, title: str, note: str = "") -> str:
    from api.rss_store import digest_markdown

    markdown = digest_markdown(list(articles), title=title, note=note)
    prefixo = "Documento-semente gerado pelo IQ OS a partir do **leitor RSS** (fontes seguidas na plataforma).\n\n"
    return f"{prefixo}{markdown}".strip() + "\n"


# --- 4. Documento do Office / dossiê guardado -------------------------------
def _markdown_documento(document: Dict[str, Any]) -> str:
    from api.office_store import export_document

    content, _media, _name = export_document(document, "md")
    return str(content or "").strip() + "\n"


def _markdown_web_search(results: Sequence[Dict[str, Any]], *, term: str, sources: Sequence[str], limit: int) -> str:
    """Markdown a partir de resultados de pesquisa (web + Search360) para semente."""
    lines: List[str] = [
        f"# Resultados de pesquisa — {term}",
        "",
        "Documento-semente gerado pelo IQ OS a partir de uma pesquisa federada. "
        "Cada entrada inclui fonte, título, resumo e ligação, para que os agentes do MiroFish "
        "construam o grafo de conhecimento e simulem tendências a partir destas evidências.",
        "",
        f"- **Termo de pesquisa**: {term}",
        f"- **Fontes consultadas**: {', '.join(sources) or 'todas'}",
        f"- **Resultados incluídos**: {len(results)}",
        "",
        "## Resultados",
        "",
    ]
    for idx, item in enumerate(results, start=1):
        title = _clean(item.get("title") or "(sem título)", 220) or "(sem título)"
        snippet = _clean(item.get("snippet") or item.get("body") or "", 800)
        url = item.get("url") or item.get("href") or ""
        source_label = item.get("source_label") or item.get("source_id") or "web"
        date = item.get("date") or "—"
        lines.append(f"### {idx}. {title}")
        lines.append("")
        lines.append(f"- **Fonte**: {source_label} · {date}")
        if snippet:
            lines.append(f"- **Resumo**: {snippet}")
        if url:
            lines.append(f"- **URL**: {url}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# --- 5. Panorama do sistema -------------------------------------------------
def _markdown_sistema(payload: Dict[str, Any]) -> str:
    partes: List[str] = [
        "# Panorama do sistema IQ OS",
        "",
        f"Retrato dos dados da plataforma à data de {datetime.now().strftime('%d/%m/%Y %H:%M')} "
        "(contratação pública, insolvências, citações em éditos, contribuintes, notícias). "
        "Valores em euros; datas em ISO 8601.",
        "",
        "## 1. Volumetria dos índices",
        "",
    ]
    volumes = payload.get("volumes") or {}
    partes.append(_table([[nome, f"{total:,}".replace(",", " ")] for nome, total in volumes.items() if total is not None], ["Índice", "Registos"]))
    partes.append("## 2. Contratação pública por ano")
    partes.append("")
    partes.append(
        _table(
            [
                [bucket.get("key_as_string") or bucket.get("key"), f"{int(bucket.get('doc_count') or 0):,}".replace(",", " "), _euro((bucket.get("valor") or {}).get("value"))]
                for bucket in (payload.get("contratos_ano") or [])
            ],
            ["Ano", "Contratos", "Valor"],
        )
    )
    partes.append("## 3. Maiores contratos publicados")
    partes.append("")
    partes.append(
        _table(
            [
                [
                    item.get("ano") or "—",
                    item.get("adjudicante") or "—",
                    (item.get("objeto") or "—")[:80],
                    _euro(item.get("valor")),
                    item.get("data") or "—",
                ]
                for item in (payload.get("maiores_contratos") or [])
            ],
            ["Ano", "Adjudicante", "Objeto", "Valor", "Publicado"],
        )
    )
    partes.append("## 4. Insolvências recentes (CIRE)")
    partes.append("")
    partes.append(
        _table(
            [
                [item.get("data") or "—", item.get("insolvente") or "—", item.get("especie") or "—", item.get("tribunal") or "—"]
                for item in (payload.get("insolvencias") or [])
            ],
            ["Data", "Insolvente", "Espécie", "Tribunal"],
        )
    )
    citacoes = payload.get("citacoes_comarca") or []
    if citacoes:
        partes.append("## 5. Citações em éditos por comarca")
        partes.append("")
        partes.append(_table([[bucket.get("key"), bucket.get("doc_count")] for bucket in citacoes], ["Comarca", "Publicações"]))
    destaques = payload.get("destaques") or []
    partes.append("## 6. Destaques")
    partes.append("")
    partes.append(_bullet(destaques))
    return "\n".join(partes).strip() + "\n"


def _panorama(*, size: int = 12) -> Dict[str, Any]:
    """Recolhe o panorama do sistema (tolerante a índices/ campos ausentes)."""
    from api.elasticsearch_client import (
        ANALISES_EMPRESA_INDEX,
        CITACOES_INDEX,
        CIRE_INDEX,
        CONTRACTS_INDEX,
        CONTRIBUINTES_INDEX,
        ENTITIES_INDEX,
        GLOBAL_PADROES_INDEX,
        PEOPLE_INDEX,
        SOCIETARIO_INDEX,
    )

    es = _es()
    volumes: Dict[str, Optional[int]] = {}
    for label, index in [
        ("Contratos (Portal BASE)", CONTRACTS_INDEX),
        ("Entidades (cadastro)", ENTITIES_INDEX),
        ("Pessoas (registo societário)", PEOPLE_INDEX),
        ("Insolvências (CIRE)", CIRE_INDEX),
        ("Citações em éditos", CITACOES_INDEX),
        ("Contribuintes", CONTRIBUINTES_INDEX),
        ("Publicações societárias", SOCIETARIO_INDEX),
        ("Análises de empresa", ANALISES_EMPRESA_INDEX),
        ("Sinalizações (padrões globais)", GLOBAL_PADROES_INDEX),
    ]:
        volumes[label] = _safe_count(es, index)

    contratos_ano = _buckets(
        _safe_search(
            es,
            CONTRACTS_INDEX,
            {
                "size": 0,
                "aggs": {"por_ano": {"terms": {"field": "Ano", "size": 12, "order": {"_key": "desc"}}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}}},
            },
        ),
        "por_ano",
    )
    maiores = _hits(
        _safe_search(
            es,
            CONTRACTS_INDEX,
            {
                "size": size,
                "sort": [{"precoContratual": {"order": "desc", "unmapped_type": "double"}}],
                "_source": ["objectoContrato", "precoContratual", "Ano", "dataPublicacao", "adjudicantes", "adjudicatarios"],
            },
        )
    )
    insolvencias = _hits(
        _safe_search(
            es,
            CIRE_INDEX,
            {"size": size, "sort": [{"data_publicacao": {"order": "desc", "unmapped_type": "date"}}], "_source": ["insolvente", "especie", "tribunal", "data_publicacao"]},
        )
    )
    citacoes_comarca = _buckets(
        _safe_search(es, CITACOES_INDEX, {"size": 0, "aggs": {"comarca": {"terms": {"field": "comarca_judicial", "size": 8}}}}),
        "comarca",
    )

    def _name(parties: Any) -> str:
        """Nome da 1.ª parte. No Portal BASE `adjudicantes` é `{raw, parsed:[{nif,nome}]}`."""
        entries = parties if isinstance(parties, list) else [parties] if isinstance(parties, dict) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            parsed = entry.get("parsed")
            parsed_entries = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else [entry]
            for item in parsed_entries:
                if isinstance(item, dict) and item.get("nome"):
                    return str(item["nome"])
                if isinstance(item, dict) and item.get("nombre"):
                    return str(item["nombre"])
        return ""

    def _adjudicante(source: Dict[str, Any]) -> str:
        nome = _name(source.get("adjudicantes"))
        return nome or _name(source.get("adjudicatarios"))

    destaques: List[str] = []
    maior_contrato = max((item for item in maiores if (item.get("_source") or {}).get("precoContratual")), key=lambda hit: (hit.get("_source") or {}).get("precoContratual") or 0, default=None)
    if maior_contrato:
        source = maior_contrato.get("_source") or {}
        destaques.append(
            f"Maior contrato publicado: {_adjudicante(source) or '—'} — {_euro(source.get('precoContratual'))} "
            f"({(source.get('objectoContrato') or '—')[:70]})"
        )
    if citacoes_comarca:
        destaques.append(f"Comarca com mais éditos: {citacoes_comarca[0].get('key')} ({citacoes_comarca[0].get('doc_count')} publicações)")
    if volumes.get("Contratos (Portal BASE)"):
        destaques.append(f"Base de contratação pública: {volumes['Contratos (Portal BASE)']:,} contratos indexados".replace(",", " "))
    if volumes.get("Insolvências (CIRE)"):
        destaques.append(f"Insolvências no CIRE: {volumes['Insolvências (CIRE)']:,} publicações".replace(",", " "))

    # A mesma insolvência aparece em vários documentos do CIRE: fica uma por
    # (insolvente, data, espécie) para o mundo simulado não nascer enviesado.
    insolvencias_unicas: List[Dict[str, Any]] = []
    vistos: set = set()
    for hit in insolvencias:
        source = hit.get("_source") or {}
        chave = (source.get("insolvente"), source.get("data_publicacao"), source.get("especie"))
        if chave in vistos:
            continue
        vistos.add(chave)
        insolvencias_unicas.append(
            {
                "data": source.get("data_publicacao"),
                "insolvente": source.get("insolvente"),
                "especie": source.get("especie"),
                "tribunal": source.get("tribunal"),
            }
        )
    return {
        "volumes": volumes,
        "contratos_ano": contratos_ano,
        "maiores_contratos": [
            {
                "ano": (hit.get("_source") or {}).get("Ano"),
                "objeto": (hit.get("_source") or {}).get("objectoContrato"),
                "valor": (hit.get("_source") or {}).get("precoContratual"),
                "data": (hit.get("_source") or {}).get("dataPublicacao"),
                "adjudicante": _adjudicante(hit.get("_source") or {}),
            }
            for hit in maiores
        ],
        "insolvencias": insolvencias_unicas,
        "citacoes_comarca": citacoes_comarca,
        "destaques": destaques,
    }


# ---------------------------------------------------------------------------
# Catálogo de fontes de dados
# ---------------------------------------------------------------------------
SOURCES: List[Dict[str, Any]] = [
    {
        "id": "empresa",
        "label": "Empresa (NIF)",
        "hint": "Ficha completa: contratos, sinais, cargos sociais, insolvências e rede.",
        "params": [
            {"name": "nif", "label": "NIF", "type": "text", "required": True, "placeholder": "ex.: 500000000"},
            {"name": "pais", "label": "País", "type": "select", "options": ["PT", "ES"], "default": "PT"},
        ],
        "requirement": (
            "Antecipe a evolução desta empresa no mercado de contratação pública nos próximos 12 meses: "
            "novos contratos, mudanças de adjudicantes, risco de insolvência e reação do mercado."
        ),
    },
    {
        "id": "tema",
        "label": "Tema (Pesquisa 360)",
        "hint": "Dossiê de um tema a partir do Pesquisa 360 (plataforma + fontes externas).",
        "params": [
            {"name": "term", "label": "Tema", "type": "text", "required": True, "placeholder": "ex.: hidrogénio verde em Portugal"},
            {"name": "limit", "label": "Itens por fonte", "type": "number", "default": 6, "min": 1, "max": 20},
        ],
        "requirement": (
            "Simule a opinião pública e o posicionamento dos agentes económicos sobre este tema nos próximos "
            "6 meses e indique os cenários mais prováveis."
        ),
    },
    {
        "id": "noticias",
        "label": "Notícias (leitor RSS)",
        "hint": "Digest das notícias seguidas na plataforma (com procura opcional por termo).",
        "params": [
            {"name": "term", "label": "Filtrar por termo", "type": "text", "placeholder": "vazio = todas"},
            {"name": "limit", "label": "Nº de notícias", "type": "number", "default": 40, "min": 5, "max": 200},
        ],
        "requirement": (
            "A partir destas notícias, simule a evolução da narrativa nos próximos 3 meses: que temas ganham "
            "força, quem os amplifica e que riscos emergem."
        ),
    },
    {
        "id": "documento",
        "label": "Documento (Office / dossiê)",
        "hint": "Usa um documento já guardado no Office como material-semente.",
        "params": [{"name": "document_id", "label": "Documento", "type": "document", "required": True}],
        "requirement": (
            "Simule os desdobramentos do que está descrito neste documento: reações dos intervenientes, "
            "alinhamentos e cenários a 6 meses."
        ),
    },
    {
        "id": "sistema",
        "label": "Panorama do sistema",
        "hint": "Retrato global dos dados da plataforma (volumetria, maiores contratos, insolvências, éditos).",
        "params": [{"name": "size", "label": "Destaques por secção", "type": "number", "default": 12, "min": 5, "max": 40}],
        "requirement": (
            "Antecipe, para os próximos 6 meses, a evolução da contratação pública e do risco empresarial em "
            "Portugal a partir deste panorama, indicando os setores e as entidades mais expostas."
        ),
    },
    {
        "id": "web_search",
        "label": "Pesquisa (web + plataforma)",
        "hint": "Pesquisa um tema e usa os resultados como material-semente para a simulação.",
        "params": [
            {"name": "term", "label": "Termo de pesquisa", "type": "text", "required": True, "placeholder": "ex.: contratação pública hospitalar Portugal"},
            {"name": "sources", "label": "Fontes", "type": "text", "placeholder": "ex.: web,wikipedia_pt,internal (vazio = todas)"},
            {"name": "limit", "label": "Resultados", "type": "number", "default": 12, "min": 1, "max": 50},
        ],
        "requirement": (
            "A partir destes resultados de pesquisa, simule a evolução do tema nos próximos 6 meses: "
            "que atores vão ganhar ou perder influência, que narrativas vão emergir e que riscos são mais prováveis."
        ),
    },
]

SOURCE_IDS = [source["id"] for source in SOURCES]

#: Chaves sem as quais o MiroFish não arranca (validadas pelo `run.py` dele).
REQUIRED_KEYS: List[Dict[str, Any]] = [
    {
        "name": "MIROFISH_LLM_API_KEY",
        "aliases": ["OPENAI_API_KEY"],
        "role": "LLM do motor: ontologia, personas, agentes e relatório",
        "where": "finance-llm/.env (passa ao contentor mirofish)",
        "detail": "Qualquer API compatível com OpenAI. Para outro fornecedor, definir também "
        "MIROFISH_LLM_BASE_URL e MIROFISH_LLM_MODEL_NAME (sem base URL assume https://api.openai.com/v1).",
    },
    {
        "name": "MIROFISH_ZEP_API_KEY",
        "aliases": ["ZEP_API_KEY"],
        "role": "Grafo de conhecimento e memória de longo prazo dos agentes (Zep Cloud)",
        "where": "finance-llm/.env (passa ao contentor mirofish)",
        "detail": "Conta e chave em https://app.getzep.com (o plano gratuito chega para uso simples).",
    },
]

COMMANDS = {
    "start": "docker compose --profile mirofish up -d",
    "recreate": "docker compose --profile mirofish up -d --force-recreate mirofish",
    "logs": "docker compose --profile mirofish logs mirofish",
    "health": "curl http://127.0.0.1:5001/health",
}


def explain_error(message: str) -> Dict[str, Any]:
    """Traduz o erro do MiroFish na causa provável (chave em falta ou inválida).

    O MiroFish devolve o erro do fornecedor tal e qual (por exemplo
    `LLM provider request failed (HTTP 401)`); sem esta tradução o utilizador vê
    um «502» e não sabe que chave tem de definir.
    """
    text = (message or "").lower()
    keys = ", ".join(key["name"] for key in REQUIRED_KEYS)
    if any(token in text for token in ("401", "403", "unauthorized", "invalid api key", "api key")):
        if "zep" in text:
            hint = (
                "A chave do Zep Cloud está em falta ou é inválida. Defina MIROFISH_ZEP_API_KEY no "
                ".env (finance-llm/.env) e recrie o contentor: "
                "docker compose --profile mirofish up -d --force-recreate mirofish."
            )
            return {"message": f"Zep Cloud recusou o pedido (chave em falta ou inválida): {message}", "key": "MIROFISH_ZEP_API_KEY", "hint": hint}
        hint = (
            "A chave do LLM está em falta ou é inválida. Defina MIROFISH_LLM_API_KEY (ou "
            "OPENAI_API_KEY) no .env (finance-llm/.env) e recrie o contentor: "
            "docker compose --profile mirofish up -d --force-recreate mirofish."
        )
        return {"message": f"O LLM do MiroFish recusou o pedido (chave em falta ou inválida): {message}", "key": "MIROFISH_LLM_API_KEY", "hint": hint}
    if "llm_api_key" in text or "zep_api_key" in text:
        return {
            "message": f"O MiroFish não arrancou: faltam chaves de configuração ({keys}).",
            "key": "MIROFISH_LLM_API_KEY / MIROFISH_ZEP_API_KEY",
            "hint": f"Ver quais faltam no arranque do contentor: {COMMANDS['logs']}.",
        }
    return {"message": message, "key": None, "hint": None}


def diagnose() -> Dict[str, Any]:
    """Estado do serviço + chaves esperadas + comandos, para a UI explicar o que falta."""
    info = health()
    host_env = {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL") or "",
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL") or "",
        "MIROFISH_LLM_API_KEY": bool(os.getenv("MIROFISH_LLM_API_KEY")),
        "MIROFISH_ZEP_API_KEY": bool(os.getenv("MIROFISH_ZEP_API_KEY")),
    }
    last_error = None
    for job in list_jobs(5):
        if job.get("status") == "failed" and job.get("error"):
            last_error = {"job": job["id"], "title": job.get("title"), "at": job.get("updated_at"), "error": job.get("error"), "hint": job.get("hint")}
            break
    return {
        "service": info,
        "keys": REQUIRED_KEYS,
        "host_env": host_env,
        # O contentor do MiroFish valida as chaves e imprime exatamente as que
        # faltam; `host_env` só mostra o que é visível do backend (o `.env` passa
        # `OPENAI_*` aos dois, mas `MIROFISH_*` só ao contentor `mirofish`).
        "note": "As chaves MIROFISH_* são lidas pelo contentor mirofish, não pelo backend — "
        "host_env confirma apenas as que o backend também vê (OPENAI_*).",
        "commands": COMMANDS,
        "last_error": last_error,
    }


def source_by_id(source_id: str) -> Optional[Dict[str, Any]]:
    return next((source for source in SOURCES if source["id"] == source_id), None)


async def build_seed(source_id: str, params: Optional[Dict[str, Any]] = None, *, session: Any = None) -> Dict[str, Any]:
    """Constrói o documento-semente (Markdown) a partir dos dados do sistema."""
    source = source_by_id(source_id)
    if source is None:
        raise MiroFishError(f"fonte desconhecida: {source_id}. Disponíveis: {', '.join(SOURCE_IDS)}")
    params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
    stats: Dict[str, Any] = {"source": source_id}

    if source_id == "empresa":
        nif = str(params.get("nif") or "").strip()
        if not nif:
            raise MiroFishError("indique o NIF da empresa")
        from api import padroes_service as padroes

        pais = str(params.get("pais") or "PT").upper()
        dossier = padroes.entity_dossier(nif, pais=pais)
        markdown = _markdown_empresa(dossier)
        title = str(dossier.get("nome") or nif)
        stats.update({"nif": nif, "contratos": len(dossier.get("contratos") or []), "sinais": len(dossier.get("sinais") or [])})

    elif source_id == "tema":
        term = str(params.get("term") or "").strip()
        if not term:
            raise MiroFishError("indique o tema a investigar")
        from api import search360_service

        dossier = asyncio.run(
            search360_service.topic(
                term,
                limit=int(params.get("limit") or 6),
                session=session,
                with_synthesis=False,
            )
        )
        markdown = _markdown_tema(dossier)
        title = f"Tema {term}"
        stats.update({"term": term, "items": len(dossier.get("items") or [])})

    elif source_id == "noticias":
        from api import rss_store

        term = str(params.get("term") or "").strip().lower()
        limit = int(params.get("limit") or 40)
        articles = [item for item in (rss_store.all_articles() or []) if isinstance(item, dict)]
        if term:
            articles = [item for item in articles if term in f"{item.get('title', '')} {item.get('summary', '')}".lower()]
        articles = articles[:limit]
        if not articles:
            raise MiroFishError("o leitor RSS não tem notícias" + (" para esse termo" if term else "") + " — recolha notícias no módulo RSS")
        title = f"Notícias{' · ' + term if term else ''} ({len(articles)})"
        markdown = _markdown_noticias(articles, title=title, note="Semente para simulação de opinião no MiroFish.")
        stats.update({"term": term or None, "artigos": len(articles)})

    elif source_id == "documento":
        document_id = str(params.get("document_id") or "").strip()
        if not document_id:
            raise MiroFishError("indique o documento do Office")
        from api import office_store

        document = office_store.get_document(document_id)
        if not document or not (document.get("markdown") or "").strip():
            raise MiroFishError(f"documento sem texto: {document_id}")
        markdown = _markdown_documento(document)
        title = document.get("title") or document_id
        stats.update({"document_id": document_id, "words": document.get("words")})

    elif source_id == "web_search":
        term = str(params.get("term") or "").strip()
        if not term:
            raise MiroFishError("indique o termo de pesquisa")
        from api import search360_service, tools

        sources_input = str(params.get("sources") or "").strip()
        sources_ids = [part.strip() for part in sources_input.split(",") if part.strip()] or None
        limit = max(1, min(50, int(params.get("limit") or 12)))

        # Tenta primeiro a pesquisa federada do Search360 (inclui web quando configurado).
        try:
            dossier = await search360_service.search(term, sources_ids=sources_ids, limit=limit, scope=None)
            results = dossier.get("items") or []
        except Exception as exc:
            logger.warning("mirofish web_search: Search360 falhou (%s), a recuar para web_search directo", exc)
            results = []

        # Se não veio nada ou o utilizador pediu apenas web, recai para o motor de pesquisa web.
        if not results and (sources_ids is None or "web" in sources_ids):
            raw = tools.web_search(term, max_results=limit, source="auto")
            results = [item for item in (raw or []) if not item.get("error")]

        if not results:
            raise MiroFishError(f"a pesquisa não devolveu resultados para: {term}")

        sources_used = [item.get("source_id") or item.get("source") or "web" for item in results]
        markdown = _markdown_web_search(results, term=term, sources=sorted(set(sources_used)), limit=len(results))
        title = f"Pesquisa: {term}"
        stats.update({"term": term, "results": len(results), "sources": sorted(set(sources_used))})

    else:  # sistema
        payload = _panorama(size=int(params.get("size") or 12))
        markdown = _markdown_sistema(payload)
        title = "Panorama do sistema IQ OS"
        stats.update({"volumes": payload.get("volumes"), "destaques": len(payload.get("maiores_contratos") or [])})

    filename = f"{_slug(title)}.md"
    return {
        "source": source_id,
        "label": (source or {}).get("label"),
        "title": title,
        "filename": filename,
        "markdown": markdown,
        "chars": len(markdown),
        "words": len(markdown.split()),
        "suggested_requirement": (source or {}).get("requirement", ""),
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Trabalhos (jobs) — a simulação demora minutos e é conduzida em segundo plano
# ---------------------------------------------------------------------------
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
# Ordem de criação explícita. `created_at` **não** serve para ordenar: no
# Windows o relógio só avança a cada ~15 ms, pelo que vários trabalhos criados
# no mesmo instante partilham o timestamp — e com `reverse=True` a ordenação
# estável devolvia-os do mais antigo para o mais recente.
_JOB_SEQ = 0


def _job_new(kind: str, payload: Dict[str, Any], *, title: str) -> Dict[str, Any]:
    global _JOB_SEQ  # noqa: PLW0603 - contador do módulo, protegido pelo `_JOBS_LOCK`
    now = datetime.now().isoformat()
    with _JOBS_LOCK:
        _JOB_SEQ += 1
        job = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "title": title,
            "status": "running",
            "step": "seed",
            "progress": 2,
            "created_at": now,
            "updated_at": now,
            "seq": _JOB_SEQ,
            "log": [],
            "result": {},
            "error": None,
            "hint": None,
        }
        _JOBS[job["id"]] = job
        if len(_JOBS) > MAX_JOBS:
            for old in sorted(_JOBS.values(), key=lambda item: item.get("seq") or 0)[: len(_JOBS) - MAX_JOBS]:
                _JOBS.pop(old["id"], None)
    return job


def _job_log(job_id: str, message: str, *, step: Optional[str] = None, progress: Optional[int] = None, level: str = "info") -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["log"].append({"at": datetime.now().strftime("%H:%M:%S"), "message": message, "level": level})
        job["log"] = job["log"][-200:]
        job["updated_at"] = datetime.now().isoformat()
        if step:
            job["step"] = step
        if isinstance(progress, int):
            job["progress"] = max(0, min(100, progress))
    logger.info("mirofish[%s]: %s", job_id, message)


def _job_update(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = datetime.now().isoformat()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs(limit: int = 10) -> List[Dict[str, Any]]:
    """Trabalhos mais recentes primeiro (pela ordem de criação, não pelo relógio)."""
    with _JOBS_LOCK:
        jobs = sorted(
            _JOBS.values(),
            key=lambda item: (item.get("seq") or 0, item.get("created_at") or ""),
            reverse=True,
        )[:limit]
        return [dict(job) for job in jobs]


async def run_simulation(job_id: str, payload: Dict[str, Any], *, session: Any = None) -> None:
    """Conduz a simulação completa (chamado numa thread pelo `start_simulation_job`)."""
    steps = payload.get("steps") or {}
    do_graph = bool(steps.get("graph", True))
    do_prepare = bool(steps.get("prepare", True))
    do_run = bool(steps.get("run", True))
    do_report = bool(steps.get("report", False))
    max_rounds = payload.get("max_rounds")
    platform = str(payload.get("platform") or "parallel")
    requirement = str(payload.get("requirement") or "").strip()
    result: Dict[str, Any] = {}
    try:
        _job_log(job_id, "A recolher dados do sistema e a compor o documento-semente…", step="seed", progress=5)
        seed = await build_seed(str(payload.get("source") or "sistema"), payload.get("params") or {}, session=session)
        if not requirement:
            requirement = seed.get("suggested_requirement") or ""
        _job_log(job_id, f"Semente pronta: {seed['title']} ({seed['chars']} caracteres, {seed['words']} palavras).", progress=10)
        result["seed"] = {key: seed[key] for key in ("source", "title", "filename", "chars", "words")}
        _job_update(job_id, result=dict(result))

        with _client() as client:
            _job_log(job_id, "A criar o projeto e a gerar a ontologia (LLM)…", step="ontology", progress=15)
            project = create_project(
                client,
                files=[(seed["filename"], seed["markdown"])],
                requirement=requirement or "Simulação a partir dos dados do sistema.",
                name=str(payload.get("project_name") or seed["title"])[:120],
                context="Material-semente recolhido pelo IQ OS.",
            )
            project_id = str(project.get("project_id") or "")
            if not project_id:
                raise MiroFishError("o MiroFish não devolveu project_id")
            result.update({"project_id": project_id, "ontology": project.get("ontology")})
            _job_update(job_id, result=dict(result))
            _job_log(job_id, f"Projeto criado: {project_id}. Ontologia com {len((project.get('ontology') or {}).get('entity_types') or [])} tipos de entidade.", progress=30)

            graph_id = ""
            if do_graph:
                _job_log(job_id, "A construir o grafo de conhecimento no Zep…", step="graph", progress=35)
                building = build_graph(client, project_id)
                task_id = str(building.get("task_id") or "")
                _wait(
                    client,
                    lambda: get_task(client, task_id) if task_id else building,
                    label="Grafo",
                    log=lambda message: _job_log(job_id, message),
                )
                state = get_task(client, task_id) if task_id else {}
                graph_id = str((state.get("result") or {}).get("graph_id") or "")
                _job_log(job_id, f"Grafo construído{' (' + graph_id + ')' if graph_id else ''}.", progress=55)

            if not do_prepare:
                _job_update(job_id, status="done", progress=100, result=dict(result))
                _job_log(job_id, "Concluído (parou depois do grafo, conforme pedido).", progress=100)
                return

            _job_log(job_id, "A criar a instância de simulação…", step="simulation", progress=60)
            simulation = create_simulation(client, project_id)
            simulation_id = str(simulation.get("simulation_id") or simulation.get("id") or "")
            if not simulation_id:
                raise MiroFishError("o MiroFish não devolveu simulation_id")
            result["simulation_id"] = simulation_id
            _job_update(job_id, result=dict(result))

            _job_log(job_id, "A gerar personas e a configurar o mundo (LLM)…", step="prepare", progress=65)
            preparing = prepare_simulation(client, simulation_id)
            prepare_task = str(preparing.get("task_id") or "")
            _wait(
                client,
                lambda: prepare_status(client, task_id=prepare_task, simulation_id=simulation_id),
                label="Preparação",
                log=lambda message: _job_log(job_id, message),
            )
            _job_log(job_id, "Ambiente pronto (personas + configuração das duas plataformas).", progress=80)

            if not do_run:
                _job_update(job_id, status="done", progress=100, result=dict(result))
                _job_log(job_id, "Concluído (simulação preparada, execução não pedida).", progress=100)
                return

            _job_log(job_id, f"A arrancar a simulação{' (máx. ' + str(max_rounds) + ' rondas)' if max_rounds else ''}…", step="run", progress=85)
            start_simulation(client, simulation_id, max_rounds=max_rounds, platform=platform)
            _job_log(job_id, "Simulação em execução no MiroFish (acompanhe o progresso na página «Simulador IQ OS»).", progress=90)

            report_id = ""
            if do_report:
                _job_log(job_id, "A pedir o relatório da simulação…", step="report", progress=92)
                generated = generate_report(client, simulation_id)
                report_id = str(generated.get("report_id") or "")
                if report_id:
                    result["report_id"] = report_id
                    _job_update(job_id, result=dict(result))
                    _wait(
                        client,
                        lambda: report_status(client, report_id),
                        label="Relatório",
                        log=lambda message: _job_log(job_id, message),
                    )
                    _job_log(job_id, f"Relatório pronto: {report_id}.", progress=98)

        _job_update(job_id, status="done", progress=100, result=dict(result))
        _job_log(job_id, "Simulação conduzida com sucesso.", progress=100, level="success")
    except MiroFishError as exc:
        explained = explain_error(str(exc))
        _job_update(job_id, status="failed", error=explained["message"], hint=explained.get("hint"))
        _job_log(job_id, f"Falhou: {exc}", level="error")
        if explained.get("hint"):
            _job_log(job_id, explained["hint"], level="error")
    except Exception as exc:  # pragma: no cover - salvaguarda
        logger.exception("mirofish: simulação falhou")
        explained = explain_error(str(exc))
        _job_update(job_id, status="failed", error=explained["message"] or f"{type(exc).__name__}: {exc}", hint=explained.get("hint"))
        _job_log(job_id, f"Falhou: {type(exc).__name__}: {exc}", level="error")


def start_simulation_job(payload: Dict[str, Any], *, session: Any = None) -> Dict[str, Any]:
    """Arranca a simulação em segundo plano e devolve o *job* criado."""
    title = str(payload.get("title") or payload.get("source") or "simulação")
    job = _job_new("simulation", payload, title=title)

    def _run_in_thread(job_id: str, payload: Dict[str, Any], session: Any) -> None:
        # run_simulation contém chamadas async (build_seed); criamos o loop.
        try:
            asyncio.run(run_simulation(job_id, payload, session=session))
        except Exception as exc:
            logger.exception("mirofish: simulação falhou no arranque")
            try:
                _job_update(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
                _job_log(job_id, f"Falhou: {type(exc).__name__}: {exc}", level="error")
            except Exception:
                pass

    thread = threading.Thread(target=_run_in_thread, args=(job["id"], payload, session), daemon=True)
    thread.start()
    return job


# ---------------------------------------------------------------------------
# Simulador IQ OS — leitura dos resultados
#
# O que o enxame produziu: estado da execução, ações por ronda, elenco de
# agentes, ontologia do grafo e o relatório. Tudo o que aqui está só **lê**
# (ou pede ao MiroFish para parar/entrevistar) e aceita um `client` injetado,
# para poder ser testado sem o serviço a correr.
# ---------------------------------------------------------------------------
#: Estado da execução/relatório → etiqueta em português e tom visual.
RUN_STATE_LABELS: Dict[str, Tuple[str, str]] = {
    "idle": ("por arrancar", "idle"),
    "created": ("criada", "idle"),
    "ready": ("pronta a correr", "idle"),
    "pending": ("à espera", "idle"),
    "preparing": ("a preparar", "busy"),
    "planning": ("a planear", "busy"),
    "starting": ("a arrancar", "busy"),
    "generating": ("a escrever", "busy"),
    "running": ("em curso", "busy"),
    "paused": ("em pausa", "busy"),
    "stopping": ("a parar", "busy"),
    "stopped": ("interrompida", "warn"),
    "completed": ("concluída", "ok"),
    "success": ("concluída", "ok"),
    "failed": ("falhou", "error"),
    "error": ("falhou", "error"),
    "timeout": ("expirou", "error"),
}

#: Estados em que a execução ainda está a mexer (relatório ainda não pode ser pedido).
ACTIVE_RUN_STATES = {"starting", "running", "paused", "stopping", "preparing", "created", "ready"}

#: Ações dos agentes → etiqueta em português.
ACTION_LABELS: Dict[str, str] = {
    "CREATE_POST": "publicou",
    "CREATE_COMMENT": "comentou",
    "LIKE_POST": "gostou",
    "LIKE_COMMENT": "gostou de um comentário",
    "DISLIKE_POST": "não gostou",
    "DISLIKE_COMMENT": "não gostou de um comentário",
    "REPOST": "repartilhou",
    "QUOTE_POST": "citou",
    "FOLLOW": "seguiu",
    "SEARCH_POSTS": "pesquisou",
    "SEARCH_USER": "procurou utilizadores",
    "DO_NOTHING": "nada fez",
    "TREND": "tendência",
}


def run_state_label(state: Any) -> Dict[str, str]:
    """Etiqueta em português para um estado do MiroFish (`running`, `completed`…)."""
    key = str(state or "").strip().lower() or "idle"
    label, tone = RUN_STATE_LABELS.get(key, (key.replace("_", " "), "idle"))
    return {"key": key, "label": label, "tone": tone}


def action_label(action_type: Any) -> str:
    """Verbo em português para o tipo de ação (`CREATE_POST` → «publicou»)."""
    key = str(action_type or "").strip().upper()
    return ACTION_LABELS.get(key, key.replace("_", " ").lower() or "agiu")


@contextmanager
def _client_or(client: Optional[httpx.Client] = None, timeout: float = 90.0) -> Iterator[httpx.Client]:
    """Usa o cliente dado (testes) ou abre um novo para o MiroFish."""
    if client is not None:
        yield client
        return
    with _client(timeout) as created:
        yield created


def _get(client: httpx.Client, path: str, *, params: Optional[Dict[str, Any]] = None, action: str = "") -> Dict[str, Any]:
    clean = {key: value for key, value in (params or {}).items() if value not in (None, "")}
    return _payload(client.get(path, params=clean), action or f"leitura de {path}")


def _post(client: httpx.Client, path: str, body: Optional[Dict[str, Any]] = None, *, action: str = "") -> Dict[str, Any]:
    return _payload(client.post(path, json=body or {}), action or f"pedido a {path}")


def _safe(fetch: Callable[[], Dict[str, Any]], fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Executa uma leitura tolerante: um endpoint ausente não derruba a página."""
    try:
        return fetch() or (fallback or {})
    except Exception as exc:  # noqa: BLE001 - a página mostra o resto na mesma
        logger.warning("mirofish: leitura falhou (%s)", exc)
        return fallback or {}


# --- acessos diretos -------------------------------------------------------
def simulation_detail(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/simulation/{id}` — ficha da simulação."""
    return _get(client, f"/api/simulation/{simulation_id}", action="ficha da simulação")


def simulation_config(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/config` — configuração do mundo e dos agentes."""
    return _get(client, f"/api/simulation/{simulation_id}/config", action="configuração da simulação")


def simulation_profiles(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/profiles` — personas geradas (elenco)."""
    return _get(client, f"/api/simulation/{simulation_id}/profiles", action="personas")


def run_status_detail(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/run-status/detail` — estado + ações recentes."""
    return _get(client, f"/api/simulation/{simulation_id}/run-status/detail", action="estado detalhado")


def run_timeline(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/timeline` — atividade por ronda."""
    return _get(client, f"/api/simulation/{simulation_id}/timeline", action="cronologia")


def run_agent_stats(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/agent-stats` — ações por agente."""
    return _get(client, f"/api/simulation/{simulation_id}/agent-stats", action="estatísticas dos agentes")


def run_actions(
    client: httpx.Client,
    simulation_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    platform: Optional[str] = None,
    agent_id: Optional[int] = None,
    round_num: Optional[int] = None,
) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/actions` — feed de ações dos agentes."""
    return _get(
        client,
        f"/api/simulation/{simulation_id}/actions",
        params={
            "limit": max(1, min(500, int(limit))),
            "offset": max(0, int(offset)),
            "platform": platform,
            "agent_id": agent_id,
            "round_num": round_num,
        },
        action="ações dos agentes",
    )


def project_detail(client: httpx.Client, project_id: str) -> Dict[str, Any]:
    """`GET /api/graph/project/{id}` — projeto, ontologia e grafo construído."""
    return _get(client, f"/api/graph/project/{project_id}", action="projeto")


def graph_data(client: httpx.Client, graph_id: str) -> Dict[str, Any]:
    """`GET /api/graph/data/{graph_id}` — nós e factos do grafo de conhecimento (Zep)."""
    return _get(client, f"/api/graph/data/{graph_id}", action="grafo de conhecimento")


# --- ações na simulação (o que o MiroFish deixa fazer) ----------------------
def env_status(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`POST /api/simulation/env-status` — o ambiente está vivo (aceita entrevistas)?"""
    return _post(client, "/api/simulation/env-status", {"simulation_id": simulation_id}, action="estado do ambiente")


def close_env(client: httpx.Client, simulation_id: str, *, timeout: int = 30) -> Dict[str, Any]:
    """`POST /api/simulation/close-env` — fecha o ambiente de forma graciosa."""
    return _post(
        client,
        "/api/simulation/close-env",
        {"simulation_id": simulation_id, "timeout": timeout},
        action="fecho do ambiente",
    )


def restart_simulation(
    client: httpx.Client,
    simulation_id: str,
    *,
    max_rounds: Optional[int] = None,
    platform: str = "parallel",
    force: bool = True,
    memory_update: bool = False,
) -> Dict[str, Any]:
    """`POST /api/simulation/start` — arranca (ou reinicia, com `force`) a execução."""
    body: Dict[str, Any] = {
        "simulation_id": simulation_id,
        "platform": platform,
        "force": force,
        "enable_graph_memory_update": memory_update,
    }
    if max_rounds:
        body["max_rounds"] = int(max_rounds)
    return _post(client, "/api/simulation/start", body, action="arranque da simulação")


def interview_batch(
    client: httpx.Client,
    simulation_id: str,
    interviews: Sequence[Dict[str, Any]],
    *,
    timeout: int = 300,
) -> Dict[str, Any]:
    """`POST /api/simulation/interview/batch` — a mesma pergunta (ou várias) a vários agentes."""
    return _post(
        client,
        "/api/simulation/interview/batch",
        {"simulation_id": simulation_id, "interviews": list(interviews), "timeout": timeout},
        action="entrevistas em lote",
    )


def simulation_posts(
    client: httpx.Client,
    simulation_id: str,
    *,
    platform: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/posts` — publicações do mundo simulado."""
    return _get(
        client,
        f"/api/simulation/{simulation_id}/posts",
        params={"platform": platform, "limit": limit, "offset": offset},
        action="publicações da simulação",
    )


def simulation_comments(
    client: httpx.Client,
    simulation_id: str,
    *,
    platform: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
) -> Dict[str, Any]:
    """`GET /api/simulation/{id}/comments` — comentários do mundo simulado."""
    return _get(
        client,
        f"/api/simulation/{simulation_id}/comments",
        params={"platform": platform, "limit": limit, "offset": offset},
        action="comentários da simulação",
    )


def report_logs(client: httpx.Client, report_id: str, kind: str = "console", *, from_line: int = 0) -> Dict[str, Any]:
    """`GET /api/report/{id}/console-log|agent-log` — o que o relatório está a fazer."""
    suffix = "agent-log" if kind == "agent" else "console-log"
    return _get(
        client,
        f"/api/report/{report_id}/{suffix}",
        params={"from_line": from_line},
        action=f"registo do relatório ({suffix})",
    )


def graph_search(client: httpx.Client, graph_id: str, query: str, *, limit: int = 10) -> Dict[str, Any]:
    """`POST /api/report/tools/search` — pesquisa semântica no grafo (factos e nós)."""
    return _post(
        client,
        "/api/report/tools/search",
        {"graph_id": graph_id, "query": query, "limit": limit},
        action="pesquisa no grafo",
    )


def graph_statistics(client: httpx.Client, graph_id: str) -> Dict[str, Any]:
    """`POST /api/report/tools/statistics` — estatísticas do grafo (nós, factos, tipos)."""
    return _post(client, "/api/report/tools/statistics", {"graph_id": graph_id}, action="estatísticas do grafo")


def report_check(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`GET /api/report/check/{sim}` — há relatório? entrevistas desbloqueadas?"""
    return _get(client, f"/api/report/check/{simulation_id}", action="estado do relatório")


def report_by_simulation(client: httpx.Client, simulation_id: str) -> Optional[Dict[str, Any]]:
    """`GET /api/report/by-simulation/{sim}` — relatório existente (ou `None`)."""
    try:
        return _get(client, f"/api/report/by-simulation/{simulation_id}", action="relatório da simulação")
    except MiroFishError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def report_sections(client: httpx.Client, report_id: str) -> Dict[str, Any]:
    """`GET /api/report/{id}/sections` — secções já escritas."""
    return _get(client, f"/api/report/{report_id}/sections", action="secções do relatório")


def stop_simulation(client: httpx.Client, simulation_id: str) -> Dict[str, Any]:
    """`POST /api/simulation/stop` — para a execução."""
    return _post(client, "/api/simulation/stop", {"simulation_id": simulation_id}, action="parar a simulação")


def interview_agent(
    client: httpx.Client,
    simulation_id: str,
    prompt: str,
    *,
    agent_id: int,
    platform: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """`POST /api/simulation/interview` — pergunta a um agente do enxame."""
    body: Dict[str, Any] = {"simulation_id": simulation_id, "agent_id": agent_id, "prompt": prompt, "timeout": timeout}
    if platform:
        body["platform"] = platform
    return _post(client, "/api/simulation/interview", body, action="entrevista ao agente")


def interview_all(
    client: httpx.Client,
    simulation_id: str,
    prompt: str,
    *,
    platform: Optional[str] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """`POST /api/simulation/interview/all` — a mesma pergunta a todos os agentes."""
    body: Dict[str, Any] = {"simulation_id": simulation_id, "prompt": prompt, "timeout": timeout}
    if platform:
        body["platform"] = platform
    return _post(client, "/api/simulation/interview/all", body, action="entrevista a todos os agentes")


def report_chat(client: httpx.Client, simulation_id: str, message: str, *, history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """`POST /api/report/chat` — conversa com o agente de relatório."""
    return _post(
        client,
        "/api/report/chat",
        {"simulation_id": simulation_id, "message": message, "chat_history": history or []},
        action="conversa com o relatório",
    )


# --- normalização ----------------------------------------------------------
def _title(item: Dict[str, Any], fallback: str) -> str:
    for key in ("title", "name", "project_name", "simulation_requirement"):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:120]
    return fallback


def _ontology_types(items: Any, *, limit: int = 40) -> List[str]:
    names: List[str] = []
    for item in items or []:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("type") or item.get("label") or "").strip()
        else:
            name = ""
        if name and name not in names:
            names.append(name)
    return names[:limit]


def _action_item(raw: Dict[str, Any], *, index: int) -> Dict[str, Any]:
    args = raw.get("action_args") if isinstance(raw.get("action_args"), dict) else {}
    platform = str(raw.get("platform") or "").strip().lower()
    return {
        "id": f"{raw.get('timestamp') or index}-{raw.get('agent_id')}-{index}",
        "agent_id": raw.get("agent_id"),
        "agent_name": raw.get("agent_name") or f"Agente {raw.get('agent_id')}",
        "action_type": raw.get("action_type"),
        "action": action_label(raw.get("action_type")),
        "platform": platform,
        "round": raw.get("round_num"),
        "timestamp": raw.get("timestamp"),
        "success": bool(raw.get("success", True)),
        "content": str(args.get("content") or args.get("text") or "").strip(),
        "target": str(args.get("target") or args.get("post_id") or args.get("comment_id") or args.get("user_id") or "").strip(),
    }


def _report_summary(report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not report:
        return None
    markdown = str(report.get("markdown_content") or "")
    outline = report.get("outline") if isinstance(report.get("outline"), dict) else {}
    return {
        "report_id": report.get("report_id"),
        "simulation_id": report.get("simulation_id"),
        "status": run_state_label(report.get("status")),
        "title": outline.get("title") or "Relatório da simulação",
        "summary": outline.get("summary") or "",
        "requirement": report.get("simulation_requirement") or "",
        "created_at": report.get("created_at"),
        "completed_at": report.get("completed_at"),
        "error": report.get("error"),
        "chars": len(markdown),
        "words": len(markdown.split()),
        "markdown": markdown,
        "sections": [
            {
                "title": section.get("title") or f"Secção {index + 1}",
                "chars": len(str(section.get("content") or "")),
                "content": str(section.get("content") or ""),
            }
            for index, section in enumerate(outline.get("sections") or [])
            if isinstance(section, dict)
        ],
    }


def _report_error(message: str) -> str:
    """Traduz as duas recusas do MiroFish ao pedir o relatório."""
    text = str(message)
    if "still active" in text:
        return "A simulação ainda está a correr (ou o grafo ainda está a ser ingerido). Pare a execução ou espere pelo fim antes de pedir o relatório."
    if "successfully completed or stopped" in text:
        return "O relatório só pode ser gerado depois de a simulação terminar (concluída ou interrompida)."
    return text


# --- leituras agregadas ----------------------------------------------------
def job_for_simulation(simulation_id: str) -> Optional[Dict[str, Any]]:
    """O trabalho da plataforma que criou esta simulação (se ainda estiver em memória)."""
    target = str(simulation_id or "")
    if not target:
        return None
    for job in list_jobs(MAX_JOBS):
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        if str(result.get("simulation_id") or "") != target:
            continue
        return {
            "id": job.get("id"),
            "title": job.get("title"),
            "status": job.get("status"),
            "step": job.get("step"),
            "progress": job.get("progress"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
            "error": job.get("error"),
            "hint": job.get("hint"),
            "seed": result.get("seed"),
            "project_id": result.get("project_id"),
            "report_id": result.get("report_id"),
            "log": (job.get("log") or [])[-25:],
        }
    return None


def runs(*, client: Optional[httpx.Client] = None, limit: int = 20, enrich: int = 6) -> Dict[str, Any]:
    """Catálogo de simulações: as do MiroFish + o trabalho da plataforma que as lançou.

    Só as `enrich` mais recentes levam estado ao vivo (ronda, progresso, relatório)
    para não multiplicar pedidos ao MiroFish.
    """
    with _client_or(client) as c:
        simulations = list_simulations(c)[: max(1, limit)]
        items: List[Dict[str, Any]] = []
        for index, simulation in enumerate(simulations):
            simulation_id = str(simulation.get("simulation_id") or simulation.get("id") or "")
            job = job_for_simulation(simulation_id)
            item: Dict[str, Any] = {
                "simulation_id": simulation_id,
                "project_id": simulation.get("project_id"),
                "graph_id": simulation.get("graph_id"),
                "title": (job or {}).get("title") or _title(simulation, f"Simulação {simulation_id}"),
                "state": run_state_label(simulation.get("status")),
                "created_at": simulation.get("created_at"),
                "updated_at": simulation.get("updated_at"),
                "profiles_count": simulation.get("profiles_count"),
                "entities_count": simulation.get("entities_count"),
                "entity_types": _ontology_types(simulation.get("entity_types")),
                "platforms": {
                    "twitter": bool(simulation.get("enable_twitter", True)),
                    "reddit": bool(simulation.get("enable_reddit", True)),
                },
                "job": {"id": (job or {}).get("id"), "status": (job or {}).get("status"), "step": (job or {}).get("step")} if job else None,
                "live": None,
                "report": None,
            }
            if simulation_id and index < enrich:
                state = _safe(lambda sid=simulation_id: run_status(c, sid))
                if state:
                    item["state"] = run_state_label(state.get("runner_status") or simulation.get("status"))
                    item["live"] = {
                        "round_current": state.get("current_round"),
                        "rounds_total": state.get("total_rounds"),
                        "progress": state.get("progress_percent"),
                        "actions_total": state.get("total_actions_count"),
                        "actions_twitter": state.get("twitter_actions_count"),
                        "actions_reddit": state.get("reddit_actions_count"),
                        "simulated_hours": state.get("simulated_hours"),
                        "hours_total": state.get("total_simulation_hours"),
                        "started_at": state.get("started_at"),
                        "completed_at": state.get("completed_at"),
                        "twitter_round": state.get("twitter_current_round"),
                        "reddit_round": state.get("reddit_current_round"),
                    }
                check = _safe(lambda sid=simulation_id: report_check(c, sid))
                if check:
                    item["report"] = {
                        "has_report": bool(check.get("has_report")),
                        "report_id": check.get("report_id"),
                        "status": run_state_label(check.get("report_status")),
                        "interview_unlocked": bool(check.get("interview_unlocked")),
                    }
            items.append(item)
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {"count": len(items), "runs": items}


def run_overview(
    simulation_id: str,
    *,
    client: Optional[httpx.Client] = None,
    actions: int = 30,
    with_cast: bool = True,
) -> Dict[str, Any]:
    """Retrato completo de uma simulação: execução, rondas, elenco, grafo e relatório."""
    with _client_or(client) as c:
        detail = simulation_detail(c, simulation_id)
        state = _safe(lambda: run_status(c, simulation_id))
        timeline = _safe(lambda: run_timeline(c, simulation_id), {"timeline": []})
        stats = _safe(lambda: run_agent_stats(c, simulation_id), {"stats": []})
        feed = _safe(lambda: run_actions(c, simulation_id, limit=actions), {"actions": []})
        check = _safe(lambda: report_check(c, simulation_id))
        project_id = str(detail.get("project_id") or "")
        project = _safe(lambda: project_detail(c, project_id)) if project_id else {}
        config = _safe(lambda: simulation_config(c, simulation_id)) if with_cast else {}
        profiles = _safe(lambda: simulation_profiles(c, simulation_id)) if with_cast else {}

    ontology = project.get("ontology") if isinstance(project.get("ontology"), dict) else {}
    rounds = [
        {
            "round": row.get("round_num"),
            "total": row.get("total_actions") or 0,
            "twitter": row.get("twitter_actions") or 0,
            "reddit": row.get("reddit_actions") or 0,
            "agents": row.get("active_agents_count") or 0,
            "types": row.get("action_types") or {},
        }
        for row in (timeline.get("timeline") or [])
        if isinstance(row, dict)
    ]
    cast = _merge_cast(config.get("agent_configs") or [], profiles.get("profiles") or [], stats.get("stats") or [])
    actions_list = [_action_item(raw, index=index) for index, raw in enumerate(feed.get("actions") or []) if isinstance(raw, dict)]
    actions_list.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    run_state = run_state_label(state.get("runner_status") or detail.get("status"))
    return {
        "simulation": {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "graph_id": detail.get("graph_id"),
            "title": _title(project, _title(detail, f"Simulação {simulation_id}")),
            "project_name": project.get("name"),
            "requirement": detail.get("config_reasoning") or project.get("simulation_requirement") or "",
            "reasoning": config.get("generation_reasoning") or "",
            "analysis": project.get("analysis_summary") or "",
            "created_at": detail.get("created_at"),
            "updated_at": detail.get("updated_at"),
            "entity_types": _ontology_types(detail.get("entity_types")) or _ontology_types(ontology.get("entity_types")),
            "profiles_count": detail.get("profiles_count"),
            "entities_count": detail.get("entities_count"),
            "ontology": {
                "entity_types": _ontology_types(ontology.get("entity_types")),
                "edge_types": _ontology_types(ontology.get("edge_types")),
            },
        },
        "state": run_state,
        "active": run_state["key"] in ACTIVE_RUN_STATES,
        "metrics": {
            "round_current": state.get("current_round"),
            "rounds_total": state.get("total_rounds"),
            "progress": state.get("progress_percent"),
            "actions_total": state.get("total_actions_count"),
            "actions_twitter": state.get("twitter_actions_count"),
            "actions_reddit": state.get("reddit_actions_count"),
            "simulated_hours": state.get("simulated_hours"),
            "hours_total": state.get("total_simulation_hours"),
            "agents_total": len(cast) or detail.get("profiles_count"),
            "entities_total": detail.get("entities_count"),
            "started_at": state.get("started_at"),
            "completed_at": state.get("completed_at"),
        },
        "platforms": {
            "twitter": {
                "running": bool(state.get("twitter_running")),
                "completed": bool(state.get("twitter_completed")),
                "round": state.get("twitter_current_round"),
                "actions": state.get("twitter_actions_count"),
            },
            "reddit": {
                "running": bool(state.get("reddit_running")),
                "completed": bool(state.get("reddit_completed")),
                "round": state.get("reddit_current_round"),
                "actions": state.get("reddit_actions_count"),
            },
        },
        "rounds": rounds,
        "actions": actions_list,
        "cast": cast,
        "state_counts": _state_counts(cast),
        "report": {
            "has_report": bool(check.get("has_report")),
            "report_id": check.get("report_id"),
            "status": run_state_label(check.get("report_status")),
            "interview_unlocked": bool(check.get("interview_unlocked")),
        },
        "job": job_for_simulation(simulation_id),
        "report_hint": _report_hint(run_state),
    }


def _report_hint(run_state: Dict[str, str]) -> Optional[str]:
    if run_state["key"] in ACTIVE_RUN_STATES:
        return "O relatório só pode ser pedido depois de a simulação terminar — pode esperar pelo fim ou interromper a execução."
    if run_state["key"] in {"failed", "error", "timeout"}:
        return "A execução falhou: o MiroFish recusa gerar relatório de uma simulação que não terminou com sucesso."
    return None


def _merge_cast(
    configs: Sequence[Dict[str, Any]],
    profiles: Sequence[Dict[str, Any]],
    stats: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Junta configuração (tipo/influência), persona (bio) e ações de cada agente."""
    by_name: Dict[str, Dict[str, Any]] = {}
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("name"):
            by_name[str(profile["name"]).strip().casefold()] = profile
    stats_by_id: Dict[Any, Dict[str, Any]] = {}
    for stat in stats:
        if isinstance(stat, dict):
            stats_by_id[stat.get("agent_id")] = stat

    cast: List[Dict[str, Any]] = []
    for config in configs:
        if not isinstance(config, dict):
            continue
        name = str(config.get("entity_name") or "").strip()
        profile = by_name.get(name.casefold(), {})
        stat = stats_by_id.get(config.get("agent_id"), {})
        cast.append(
            {
                "agent_id": config.get("agent_id"),
                "name": name or profile.get("name") or f"Agente {config.get('agent_id')}",
                "entity_type": config.get("entity_type") or "",
                "entity_uuid": config.get("entity_uuid") or "",
                "influence": config.get("influence_weight"),
                "activity": config.get("activity_level"),
                "stance": config.get("stance") or "",
                "sentiment": config.get("sentiment_bias"),
                "active_hours": config.get("active_hours") or [],
                "age": profile.get("age"),
                "gender": profile.get("gender"),
                "mbti": profile.get("mbti"),
                "country": profile.get("country"),
                "karma": profile.get("karma"),
                "topics": [str(topic) for topic in (profile.get("interested_topics") or [])][:8],
                "bio": profile.get("bio") or "",
                "persona": profile.get("persona") or "",
                "actions_total": stat.get("total_actions") or 0,
                "actions_twitter": stat.get("twitter_actions") or 0,
                "actions_reddit": stat.get("reddit_actions") or 0,
                "actions_detail": stat.get("action_types") or {},
                "first_action_at": stat.get("first_action_time"),
                "last_action_at": stat.get("last_action_time"),
            }
        )
    if cast:
        cast.sort(key=lambda agent: agent.get("actions_total") or 0, reverse=True)
    return cast


def _state_counts(cast: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Quantos agentes por tipo de entidade (para o gráfico do elenco)."""
    counts: Dict[str, int] = {}
    for agent in cast:
        key = str(agent.get("entity_type") or "sem tipo")
        counts[key] = counts.get(key, 0) + 1
    return [{"type": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: -item[1])]


def run_cast(simulation_id: str, *, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Elenco da simulação (personas + configuração + quantas ações fez cada agente)."""
    with _client_or(client) as c:
        config = _safe(lambda: simulation_config(c, simulation_id))
        profiles = _safe(lambda: simulation_profiles(c, simulation_id))
        stats = _safe(lambda: run_agent_stats(c, simulation_id), {"stats": []})
    cast = _merge_cast(config.get("agent_configs") or [], profiles.get("profiles") or [], stats.get("stats") or [])
    return {"count": len(cast), "agents": cast, "by_type": _state_counts(cast)}


#: Nó sem etiqueta de tipo (o Zep deixa alguns nós de conceito sem rótulo).
GRAPH_NODE_WITHOUT_TYPE = "Sem tipo"


def _graph_node(raw: Dict[str, Any]) -> Dict[str, Any]:
    labels = [str(label) for label in (raw.get("labels") or []) if str(label).strip()]
    return {
        "id": str(raw.get("uuid") or ""),
        "name": str(raw.get("name") or "").strip() or "(sem nome)",
        "type": labels[0] if labels else GRAPH_NODE_WITHOUT_TYPE,
        "labels": labels,
        "summary": str(raw.get("summary") or ""),
        "created_at": raw.get("created_at"),
        "attributes": raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {},
        "degree": 0,
    }


def _graph_edge(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Facto do Zep normalizado; factos expirados/invalidados ficam de fora."""
    if raw.get("expired_at") or raw.get("invalid_at"):
        return None
    source = str(raw.get("source_node_uuid") or "")
    target = str(raw.get("target_node_uuid") or "")
    if not source or not target:
        return None
    fact = str(raw.get("fact") or "").strip()
    edge_type = str(raw.get("fact_type") or raw.get("name") or "").strip()
    return {
        "id": str(raw.get("uuid") or f"{source}-{target}-{edge_type}"),
        "source": source,
        "target": target,
        "source_name": str(raw.get("source_node_name") or ""),
        "target_name": str(raw.get("target_node_name") or ""),
        "type": edge_type,
        "fact": fact,
        "valid_at": raw.get("valid_at") or (raw.get("attributes") or {}).get("reference_time"),
        "episodes": len(raw.get("episodes") or []),
    }


def run_graph(
    simulation_id: str,
    *,
    client: Optional[httpx.Client] = None,
    max_nodes: int = 150,
    max_edges: int = 500,
) -> Dict[str, Any]:
    """Grafo de conhecimento da simulação (nós, factos e tipos) pronto a desenhar.

    O Zep devolve centenas de nós em projetos grandes; para o browser desenhar sem
    arrastar, ficam os nós **mais ligados** (e as ligações entre eles), com o que
    ficou de fora reportado em `omitted`.
    """
    with _client_or(client) as c:
        detail = simulation_detail(c, simulation_id)
        project_id = str(detail.get("project_id") or "")
        graph_id = str(detail.get("graph_id") or "")
        if not graph_id and project_id:
            project = _safe(lambda: project_detail(c, project_id))
            graph_id = str(project.get("graph_id") or "")
        if not graph_id:
            raise MiroFishError("esta simulação ainda não tem grafo construído")
        data = graph_data(c, graph_id)

    nodes = [_graph_node(raw) for raw in (data.get("nodes") or []) if isinstance(raw, dict)]
    edges = [edge for edge in (_graph_edge(raw) for raw in (data.get("edges") or []) if isinstance(raw, dict)) if edge]
    by_id = {node["id"]: node for node in nodes}
    for edge in edges:
        for endpoint in (edge["source"], edge["target"]):
            node = by_id.get(endpoint)
            if node:
                node["degree"] += 1

    ranked = sorted(nodes, key=lambda node: (-node["degree"], node["name"]))
    keep = {node["id"] for node in ranked[: max(1, max_nodes)]}
    kept_nodes = [node for node in nodes if node["id"] in keep]
    kept_edges = [edge for edge in edges if edge["source"] in keep and edge["target"] in keep]
    kept_edges.sort(key=lambda edge: edge["type"])
    kept_edges = kept_edges[: max(1, max_edges)]

    types: Dict[str, int] = {}
    for node in nodes:
        types[node["type"]] = types.get(node["type"], 0) + 1
    relations: Dict[str, int] = {}
    for edge in edges:
        if edge["type"]:
            relations[edge["type"]] = relations.get(edge["type"], 0) + 1

    return {
        "simulation_id": simulation_id,
        "project_id": project_id,
        "graph_id": graph_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": kept_nodes,
        "edges": kept_edges,
        "types": [{"type": key, "count": value} for key, value in sorted(types.items(), key=lambda item: -item[1])],
        "relations": [{"type": key, "count": value} for key, value in sorted(relations.items(), key=lambda item: -item[1])],
        # Intercalado: nós soltos (leitura) e arestas densas (desenho).
        "omitted": {
            "nodes": max(0, len(nodes) - len(kept_nodes)),
            "edges": max(0, len(edges) - len(kept_edges)),
            "reason": "mostram-se os nós mais ligados para o desenho manter a legibilidade",
        },
    }



def run_feed(
    simulation_id: str,
    *,
    client: Optional[httpx.Client] = None,
    limit: int = 60,
    offset: int = 0,
    platform: Optional[str] = None,
    agent_id: Optional[int] = None,
    round_num: Optional[int] = None,
) -> Dict[str, Any]:
    """Feed de ações (o «que se disse») com filtros de plataforma, agente e ronda."""
    with _client_or(client) as c:
        feed = run_actions(
            c,
            simulation_id,
            limit=limit,
            offset=offset,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num,
        )
    items = [_action_item(raw, index=index) for index, raw in enumerate(feed.get("actions") or []) if isinstance(raw, dict)]
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return {"count": feed.get("count") or len(items), "offset": offset, "limit": limit, "actions": items}


def stop_run(simulation_id: str, *, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Para a execução (o MiroFish guarda o que já foi produzido e liberta o relatório)."""
    with _client_or(client) as c:
        result = stop_simulation(c, simulation_id)
    return {"simulation_id": simulation_id, "state": run_state_label(result.get("runner_status") or "stopped"), "detail": result}


#: Estados em que o MiroFish recusa entrevistar (o ambiente já fechou).
ENV_CLOSED_HINT = (
    "O ambiente da simulação só aceita entrevistas enquanto estiver a correr: depois do fim "
    "(ou do fecho do ambiente) o MiroFish responde «ambiente não está em execução»."
)


def _needs_running_env(message: str) -> bool:
    text = str(message).lower()
    return "env" in text and ("not running" in text or "não está" in text or "未运行" in text)


def run_environment(simulation_id: str, *, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Estado do ambiente de simulação: vivo? quais as plataformas disponíveis?"""
    with _client_or(client) as c:
        data = _safe(lambda: env_status(c, simulation_id))
    alive = bool(data.get("env_alive"))
    return {
        "simulation_id": simulation_id,
        "alive": alive,
        "platforms": {"twitter": bool(data.get("twitter_available")), "reddit": bool(data.get("reddit_available"))},
        "message": str(data.get("message") or ""),
        "interview_hint": None if alive else ENV_CLOSED_HINT,
    }


def close_environment(simulation_id: str, *, timeout: int = 30, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Fecha o ambiente (deixa de aceitar entrevistas; os dados ficam guardados)."""
    with _client_or(client, timeout=max(90.0, timeout + 60.0)) as c:
        try:
            data = close_env(c, simulation_id, timeout=timeout)
        except MiroFishError as exc:
            if _needs_running_env(str(exc)):
                return {"simulation_id": simulation_id, "closed": False, "detail": ENV_CLOSED_HINT}
            raise
    return {"simulation_id": simulation_id, "closed": True, "detail": data}


def restart_run(
    simulation_id: str,
    *,
    max_rounds: Optional[int] = None,
    platform: str = "parallel",
    force: bool = True,
    memory_update: bool = False,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Arranca a execução (ou reinicia-a, `force=True`, mantendo personas e grafo)."""
    if platform not in {"parallel", "twitter", "reddit"}:
        raise MiroFishError(f"plataforma inválida: {platform} (use parallel, twitter ou reddit)")
    if max_rounds is not None and not 1 <= int(max_rounds) <= 500:
        raise MiroFishError("o número de rondas tem de estar entre 1 e 500")
    with _client_or(client) as c:
        try:
            data = restart_simulation(
                c,
                simulation_id,
                max_rounds=max_rounds,
                platform=platform,
                force=force,
                memory_update=memory_update,
            )
        except MiroFishError as exc:
            text = str(exc)
            if "already running" in text.lower() or "já está" in text:
                raise MiroFishError(
                    "A simulação já está a correr. Use «Parar execução» antes de a reiniciar, ou aguarde pelo fim."
                ) from exc
            raise
    state = run_state_label(data.get("runner_status") or data.get("status") or "running")
    return {
        "simulation_id": simulation_id,
        "state": state,
        "max_rounds": data.get("max_rounds_applied") or max_rounds,
        "memory_update": bool(data.get("graph_memory_update_enabled", memory_update)),
        "detail": data,
    }


def interview_many(
    simulation_id: str,
    agents: Sequence[Any],
    prompt: str,
    *,
    platform: Optional[str] = None,
    timeout: int = 300,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Entrevista um conjunto de agentes: a mesma pergunta a cada um (`interview/batch`).

    `agents` aceita identificadores (`agent_id`) ou nomes (resolvidos no elenco).
    """
    question = str(prompt or "").strip()
    if not question:
        raise MiroFishError("a entrevista precisa de uma pergunta")
    if platform and platform not in {"twitter", "reddit"}:
        raise MiroFishError(f"plataforma inválida: {platform} (use twitter ou reddit)")

    ids: List[int] = []
    for item in agents or []:
        if isinstance(item, dict):
            value = item.get("agent_id")
            if value is None and item.get("name"):
                ids.append(str(item["name"]))
                continue
            value = item.get("agent_id")
        else:
            value = item
        if value is None or value == "":
            continue
        if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
            ids.append(value.strip())
            continue
        ids.append(int(value))

    if not ids:
        raise MiroFishError("escolha pelo menos um agente para entrevistar")

    with _client_or(client, timeout=max(120.0, float(timeout) + 60.0)) as c:
        names: Dict[str, Any] = {}
        if any(isinstance(item, str) for item in ids):
            cast = run_cast(simulation_id, client=c)
            names = {str(agent["name"]).strip().casefold(): agent["agent_id"] for agent in cast["agents"]}

        interviews: List[Dict[str, Any]] = []
        for item in ids:
            if isinstance(item, str):
                agent_id = names.get(item.casefold())
                if agent_id is None:
                    raise MiroFishError(f"agente não encontrado no elenco: {item}")
            else:
                agent_id = item
            entry: Dict[str, Any] = {"agent_id": agent_id, "prompt": question}
            if platform:
                entry["platform"] = platform
            interviews.append(entry)

        try:
            data = interview_batch(c, simulation_id, interviews, timeout=timeout)
        except MiroFishError as exc:
            if _needs_running_env(str(exc)):
                raise MiroFishError(f"{exc} — {ENV_CLOSED_HINT}") from exc
            raise

    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    respostas: List[Dict[str, Any]] = []
    for key, value in results.items():
        if not isinstance(value, dict):
            continue
        platform_key = str(value.get("platform") or key.split("_")[0] or "")
        respostas.append(
            {
                "agent_id": value.get("agent_id"),
                "platform": platform_key,
                "response": str(value.get("response") or value.get("error") or "").strip(),
                "error": value.get("error"),
            }
        )
    return {
        "simulation_id": simulation_id,
        "prompt": question,
        "asked": len(interviews),
        "answered": data.get("interviews_count") or len(respostas),
        "answers": respostas,
        "detail": data,
    }


def run_posts(
    simulation_id: str,
    *,
    platform: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Publicações do mundo simulado (como o MiroFish mostra na interação)."""
    with _client_or(client) as c:
        data = _safe(lambda: simulation_posts(c, simulation_id, platform=platform, limit=limit, offset=offset))
    return {
        "simulation_id": simulation_id,
        "platform": data.get("platform") or platform or "",
        "total": data.get("total") or data.get("count") or 0,
        "offset": offset,
        "posts": [item for item in (data.get("posts") or []) if isinstance(item, dict)],
    }


def run_comments(
    simulation_id: str,
    *,
    platform: Optional[str] = None,
    limit: int = 30,
    offset: int = 0,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Comentários do mundo simulado."""
    with _client_or(client) as c:
        data = _safe(lambda: simulation_comments(c, simulation_id, platform=platform, limit=limit, offset=offset))
    return {
        "simulation_id": simulation_id,
        "platform": data.get("platform") or platform or "",
        "total": data.get("total") or data.get("count") or 0,
        "offset": offset,
        "comments": [item for item in (data.get("comments") or []) if isinstance(item, dict)],
    }


def report_log(simulation_id: str, *, kind: str = "console", from_line: int = 0, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Registo do relatório (consola ou agente) — útil para ver o que está a acontecer."""
    with _client_or(client) as c:
        check = _safe(lambda: report_check(c, simulation_id))
        report_id = str(check.get("report_id") or "")
        if not report_id:
            report = _safe(lambda: report_by_simulation(c, simulation_id)) or {}
            report_id = str(report.get("report_id") or "")
        if not report_id:
            return {"simulation_id": simulation_id, "report_id": None, "kind": kind, "lines": [], "total_lines": 0, "has_more": False}
        data = _safe(lambda: report_logs(c, report_id, kind, from_line=from_line))
    lines = data.get("logs") or []
    return {
        "simulation_id": simulation_id,
        "report_id": report_id,
        "kind": "agent" if kind == "agent" else "console",
        "from_line": data.get("from_line") or from_line,
        "total_lines": data.get("total_lines") or len(lines),
        "has_more": bool(data.get("has_more")),
        "lines": lines,
    }


def _graph_id_for(simulation_id: str, client: httpx.Client) -> str:
    detail = simulation_detail(client, simulation_id)
    graph_id = str(detail.get("graph_id") or "")
    if graph_id:
        return graph_id
    project_id = str(detail.get("project_id") or "")
    if project_id:
        project = _safe(lambda: project_detail(client, project_id))
        graph_id = str(project.get("graph_id") or "")
    if not graph_id:
        raise MiroFishError("esta simulação ainda não tem grafo construído")
    return graph_id


def search_in_graph(
    simulation_id: str,
    query: str,
    *,
    limit: int = 10,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Pesquisa no grafo da simulação (a mesma ferramenta que o agente de relatório usa)."""
    text = str(query or "").strip()
    if not text:
        raise MiroFishError("a pesquisa precisa de uma pergunta")
    with _client_or(client, timeout=180.0) as c:
        graph_id = _graph_id_for(simulation_id, c)
        data = graph_search(c, graph_id, text, limit=max(1, min(50, int(limit))))
    facts = [
        {
            "fact": item.get("fact") or item.get("summary") or "",
            "name": item.get("name") or item.get("source_node_name") or "",
            "source_name": item.get("source_node_name") or "",
            "target_name": item.get("target_node_name") or "",
            "type": item.get("fact_type") or item.get("name") or "",
            "score": item.get("score"),
        }
        for item in (data.get("edges") or [])
        if isinstance(item, dict)
    ]
    nodes = [
        {
            "name": item.get("name") or "",
            "type": item.get("entity_type") or item.get("type") or "",
            "summary": item.get("summary") or "",
            "score": item.get("score"),
        }
        for item in (data.get("nodes") or [])
        if isinstance(item, dict)
    ]
    return {"simulation_id": simulation_id, "graph_id": graph_id, "query": text, "facts": facts, "nodes": nodes, "detail": data}


def graph_stats(simulation_id: str, *, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Estatísticas do grafo da simulação (contagens e tipos de entidade)."""
    with _client_or(client, timeout=180.0) as c:
        graph_id = _graph_id_for(simulation_id, c)
        data = _safe(lambda: graph_statistics(c, graph_id))
    return {
        "simulation_id": simulation_id,
        "graph_id": graph_id,
        "node_count": data.get("node_count") or data.get("total_nodes") or data.get("nodes_count") or 0,
        "edge_count": data.get("edge_count") or data.get("total_edges") or data.get("edges_count") or 0,
        "entity_types": data.get("entity_types") or data.get("labels") or [],
        "detail": data,
    }



def ask_agents(
    simulation_id: str,
    prompt: str,
    *,
    agent_id: Optional[int] = None,
    platform: Optional[str] = None,
    timeout: int = 180,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Entrevista um agente (ou todos): «o que achas que vai acontecer?»."""
    question = str(prompt or "").strip()
    if not question:
        raise MiroFishError("a entrevista precisa de uma pergunta")
    with _client_or(client, timeout=max(120.0, float(timeout) + 60.0)) as c:
        if agent_id is None:
            data = interview_all(c, simulation_id, question, platform=platform, timeout=timeout)
        else:
            data = interview_agent(c, simulation_id, question, agent_id=int(agent_id), platform=platform, timeout=timeout)
    return {"simulation_id": simulation_id, "mode": "todos" if agent_id is None else "agente", "data": data}


def run_report(
    simulation_id: str,
    *,
    generate: bool = False,
    force: bool = False,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Estado do relatório e, a pedido, o pedido de geração (assíncrono no MiroFish)."""
    with _client_or(client) as c:
        check = _safe(lambda: report_check(c, simulation_id))
        report_id = str(check.get("report_id") or "")
        started: Optional[Dict[str, Any]] = None
        if generate:
            try:
                started = generate_report(c, simulation_id, force=force)
                report_id = str(started.get("report_id") or report_id)
            except MiroFishError as exc:
                raise MiroFishError(_report_error(str(exc))) from exc
            check = _safe(lambda: report_check(c, simulation_id), check)
            report_id = str(check.get("report_id") or report_id)
        report = _safe(lambda: get_report(c, report_id)) if report_id else {}
    return {
        "simulation_id": simulation_id,
        "has_report": bool(report or check.get("has_report")),
        "report_id": report_id or None,
        "status": run_state_label(check.get("report_status") or report.get("status")),
        "interview_unlocked": bool(check.get("interview_unlocked")),
        "started": bool(started),
        "report": _report_summary(report),
    }


def ask_report(
    simulation_id: str,
    message: str,
    *,
    history: Optional[List[Dict[str, Any]]] = None,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Pergunta ao agente que escreveu o relatório (com o grafo como fonte)."""
    question = str(message or "").strip()
    if not question:
        raise MiroFishError("a pergunta não pode estar vazia")
    with _client_or(client, timeout=180.0) as c:
        data = report_chat(c, simulation_id, question, history=history)
    return {
        "simulation_id": simulation_id,
        "answer": str(data.get("response") or "").strip(),
        "tools": data.get("tool_calls") or [],
        "sources": data.get("sources") or [],
    }
