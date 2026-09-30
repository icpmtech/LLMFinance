"""Recolha e pesquisa das **listas públicas de devedores**.

Duas fontes oficiais:

* **Finanças (AT)** — 12 PDF publicados em
  `static.portaldasfinancas.gov.pt/app/devedores_static/`: 6 escalões de
  *contribuintes singulares* (`listaFS1..6.pdf`) e 6 de *contribuintes
  colectivos* (`listaFC1..6.pdf`). Cada PDF traz, no cabeçalho, o escalão da
  dívida e a data de atualização da lista, e depois pares **NIF/NIPC + nome**;
  o valor da dívida **não** é publicado por devedor (só o escalão).
* **Segurança Social** — a lista é consultável em
  `seg-social.pt/ptss/sef/lista-de-devedores/consulta-lista-de-devedores`
  (aplicação JSF com pesquisa por tipo de entidade, escalão, nome e NIF). Esta
  aplicação recusa pedidos automáticos (responde 404 a clientes que não sejam um
  browser interactivo), pelo que a recolha da SS é **experimental** e falha com
  uma mensagem clara; os dados podem entrar na mesma pelo JSON importado.

De cada ficheiro ficam guardados **três coisas**: o PDF original, **um ficheiro
JSON com os registos e os metadados** (incluindo a **data da recolha**) e os
registos indexados no Elasticsearch (`finance_devedores`), com o histórico das
recolhas em `finance_devedores_recolhas`.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import threading
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Catálogo das fontes
# ---------------------------------------------------------------------------

BASE_FINANCAS = "https://static.portaldasfinancas.gov.pt/app/devedores_static"
PAGINA_INDEXACAO = "https://static.portaldasfinancas.gov.pt/app/devedores_static/de-devedores.html"
SS_URL = "https://www.seg-social.pt/ptss/sef/lista-de-devedores/consulta-lista-de-devedores"

#: Ficheiros do Portal das Finanças, pela ordem em que aparecem na página oficial.
#: `valor_max=None` significa «sem limite superior».
FICHEIROS_FINANCAS: List[Dict[str, Any]] = [
    {"ficheiro": "listaFS1.pdf", "tipo": "singulares", "escalao": "7.500 a 25.000 €", "valor_min": 7500.0, "valor_max": 25000.0},
    {"ficheiro": "listaFS2.pdf", "tipo": "singulares", "escalao": "25.001 a 50.000 €", "valor_min": 25001.0, "valor_max": 50000.0},
    {"ficheiro": "listaFS3.pdf", "tipo": "singulares", "escalao": "50.001 a 100.000 €", "valor_min": 50001.0, "valor_max": 100000.0},
    {"ficheiro": "listaFS4.pdf", "tipo": "singulares", "escalao": "100.001 a 250.000 €", "valor_min": 100001.0, "valor_max": 250000.0},
    {"ficheiro": "listaFS5.pdf", "tipo": "singulares", "escalao": "250.001 a 1.000.000 €", "valor_min": 250001.0, "valor_max": 1000000.0},
    {"ficheiro": "listaFS6.pdf", "tipo": "singulares", "escalao": "mais de 1.000.000 €", "valor_min": 1000000.01, "valor_max": None},
    {"ficheiro": "listaFC1.pdf", "tipo": "coletivos", "escalao": "10.000 a 50.000 €", "valor_min": 10000.0, "valor_max": 50000.0},
    {"ficheiro": "listaFC2.pdf", "tipo": "coletivos", "escalao": "50.001 a 100.000 €", "valor_min": 50001.0, "valor_max": 100000.0},
    {"ficheiro": "listaFC3.pdf", "tipo": "coletivos", "escalao": "100.001 a 500.000 €", "valor_min": 100001.0, "valor_max": 500000.0},
    {"ficheiro": "listaFC4.pdf", "tipo": "coletivos", "escalao": "500.001 a 1.000.000 €", "valor_min": 500001.0, "valor_max": 1000000.0},
    {"ficheiro": "listaFC5.pdf", "tipo": "coletivos", "escalao": "1.000.001 a 5.000.000 €", "valor_min": 1000001.0, "valor_max": 5000000.0},
    {"ficheiro": "listaFC6.pdf", "tipo": "coletivos", "escalao": "mais de 5.000.000 €", "valor_min": 5000000.01, "valor_max": None},
]

#: Escalões da Segurança Social (o formulário da lista tem estas opções).
ESCALOES_SS: List[Dict[str, Any]] = [
    {"chave": "a", "escalao": "7.500 a 25.000 €", "valor_min": 7500.0, "valor_max": 25000.0},
    {"chave": "b", "escalao": "25.000,01 a 50.000 €", "valor_min": 25000.01, "valor_max": 50000.0},
    {"chave": "c", "escalao": "50.000,01 a 100.000 €", "valor_min": 50000.01, "valor_max": 100000.0},
    {"chave": "d", "escalao": "100.000,01 a 250.000 €", "valor_min": 100000.01, "valor_max": 250000.0},
    {"chave": "e", "escalao": "250.000,01 a 1.000.000 €", "valor_min": 250000.01, "valor_max": 1000000.0},
    {"chave": "f", "escalao": "mais de 1.000.000 €", "valor_min": 1000000.01, "valor_max": None},
]

#: Tipos de entidade na lista da Segurança Social (valores do formulário).
TIPOS_SS = [{"chave": "2", "tipo": "singulares"}, {"chave": "1", "tipo": "coletivos"}]

ENTIDADES = {
    "financas": "Autoridade Tributária (Finanças)",
    "seguranca_social": "Segurança Social",
}

TIPOS_LABEL = {"singulares": "Contribuintes singulares", "coletivos": "Contribuintes coletivos"}

# ---------------------------------------------------------------------------
# Pastas e manifesto
# ---------------------------------------------------------------------------

EXPORT_DIR_ENV = "DEVEDORES_EXPORT_DIR"
_DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[1] / "data" / "devedores"
_MANIFEST = "_manifest.json"

#: Trabalhos de recolha (id → estado).
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 20
_RUNNING = "running"

#: Linhas de cabeçalho/rodapé dos PDF (não são devedores).
_IGNORAR = (
    "contribuintes singulares",
    "contribuintes colectivos",
    "contribuintes coletivos",
    "devedores de",
    "informação actualizada",
    "informacao actualizada",
    "informação atualizada",
    "informacao atualizada",
    "nif",
    "nipc",
    "nome",
    "designação",
    "designacao",
    "página",
    "pagina",
)

_NIF_RE = re.compile(r"^\d{9}$")
_ESCALAO_RE = re.compile(r"devedores de\s+(.+?)\s*€?\s*$", re.IGNORECASE)
_DATA_LISTA_RE = re.compile(r"actualizada em\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def export_dir() -> Path:
    """Pasta raiz dos dados de devedores (criada se não existir)."""
    raw = (os.environ.get(EXPORT_DIR_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else _DEFAULT_EXPORT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def pdf_dir() -> Path:
    caminho = export_dir() / "pdf"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def json_dir() -> Path:
    caminho = export_dir() / "json"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def _manifest_path() -> Path:
    return export_dir() / _MANIFEST


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hoje() -> str:
    return date.today().isoformat()


def _slug(valor: str) -> str:
    """Nome de ficheiro seguro (sem acentos, sem espaços)."""
    normalizado = unicodedata.normalize("NFKD", str(valor))
    sem_acentos = "".join(c for c in normalizado if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9._-]+", "-", sem_acentos).strip("-")


def read_manifest() -> Dict[str, Any]:
    """Manifesto das recolhas (ficheiro → resumo)."""
    path = _manifest_path()
    if not path.exists():
        return {"generated_at": None, "recolhas": {}, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - manifesto ilegível não pode travar o módulo
        logger.warning("Manifesto de devedores ilegível (%s): %s", path, exc)
        return {"generated_at": None, "recolhas": {}, "entries": []}
    if not isinstance(data, dict):
        return {"generated_at": None, "recolhas": {}, "entries": []}
    data.setdefault("recolhas", {})
    return data


def _write_manifest(manifest: Dict[str, Any]) -> None:
    manifest["generated_at"] = _now()
    path = _manifest_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _recolha_id(entidade: str, ficheiro: str, recolhido_em: str) -> str:
    return f"{entidade}:{ficheiro}:{recolhido_em[:10]}"


def registar_recolha(entrada: Dict[str, Any]) -> Dict[str, Any]:
    """Regista no manifesto uma recolha (ficheiro + data)."""
    manifest = read_manifest()
    recolha_id = entrada.get("recolha_id") or _recolha_id(
        str(entrada.get("entidade") or ""), str(entrada.get("ficheiro") or ""), str(entrada.get("collected_at") or "")
    )
    entrada = {**entrada, "recolha_id": recolha_id}
    manifest["recolhas"][recolha_id] = entrada
    _write_manifest(manifest)
    return entrada


def list_recolhas() -> Dict[str, Any]:
    """Recolhas registadas (mais recentes primeiro)."""
    manifest = read_manifest()
    entradas = list((manifest.get("recolhas") or {}).values())
    entradas.sort(key=lambda item: str(item.get("collected_at") or ""), reverse=True)
    return {
        "dir": str(export_dir()),
        "dir_env": EXPORT_DIR_ENV,
        "generated_at": manifest.get("generated_at"),
        "total": len(entradas),
        "registos": sum(int(item.get("registos") or 0) for item in entradas),
        "items": entradas,
    }


# ---------------------------------------------------------------------------
# Catálogo (fontes + ficheiros existentes)
# ---------------------------------------------------------------------------

def fontes() -> Dict[str, Any]:
    """Catálogo das fontes e dos ficheiros publicados por cada uma."""
    manifest = read_manifest().get("recolhas") or {}
    recolhidos = {str(item.get("ficheiro")): item for item in manifest.values()}

    financas: List[Dict[str, Any]] = []
    for spec in FICHEIROS_FINANCAS:
        recolha = next(
            (
                item
                for chave, item in manifest.items()
                if str(item.get("ficheiro")) == spec["ficheiro"] and str(item.get("entidade")) == "financas"
            ),
            None,
        )
        financas.append(
            {
                **spec,
                "entidade": "financas",
                "tipo_label": TIPOS_LABEL.get(spec["tipo"], spec["tipo"]),
                "url": f"{BASE_FINANCAS}/{spec['ficheiro']}",
                "recolhido": bool(recolha),
                "collected_at": (recolha or {}).get("collected_at"),
                "registos": (recolha or {}).get("registos"),
                "lista_atualizada_em": (recolha or {}).get("lista_atualizada_em"),
            }
        )

    return {
        "entidades": ENTIDADES,
        "tipos": TIPOS_LABEL,
        "financas": {
            "pagina": PAGINA_INDEXACAO,
            "base": BASE_FINANCAS,
            "ficheiros": financas,
            "total": len(financas),
            "recolhidos": sum(1 for item in financas if item["recolhido"]),
        },
        "seguranca_social": {
            "url": SS_URL,
            "escaloes": ESCALOES_SS,
            "tipos": TIPOS_SS,
            "recolhido": any(str(item.get("entidade")) == "seguranca_social" for item in manifest.values()),
            "nota": (
                "A consulta pública da Segurança Social é uma aplicação interactiva que recusa "
                "pedidos automáticos (responde «404» a clientes que não sejam um browser). A recolha "
                "automática fica assinalada como experimental e pode ser completada pelo JSON importado."
            ),
        },
        "ficheiros_recolhidos": sorted(recolhidos.keys()),
    }


# ---------------------------------------------------------------------------
# Descarregamento e leitura do PDF
# ---------------------------------------------------------------------------

def descarregar_pdf(url: str, *, timeout: int = 180) -> Tuple[bytes, Dict[str, str]]:
    """Descarrega um PDF oficial e devolve `(conteúdo, cabeçalhos)`."""
    import requests

    resposta = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IQ-OS/1.0"},
    )
    resposta.raise_for_status()
    return resposta.content, {k.lower(): str(v) for k, v in resposta.headers.items()}


def _limpar_linha(linha: str) -> str:
    return re.sub(r"\s+", " ", linha.replace("\u00a0", " ")).strip()


def _e_cabecalho(linha: str) -> bool:
    baixa = linha.lower()
    return any(baixa.startswith(prefixo) for prefixo in _IGNORAR)


def parse_pdf(conteudo: bytes, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Lê um PDF oficial e devolve os metadados + registos.

    Cada página repete o cabeçalho (`Contribuintes singulares/colectivos`,
    `Devedores de X a Y €`, `Informação actualizada em AAAA-MM-DD`, `NIF`/`NIPC` e
    `NOME`/`DESIGNAÇÃO`); os devedores vêm a seguir, em pares **NIF/NIPC + nome**.
    Um nome muito longo pode ocupar duas linhas — nesse caso junta-se.
    """
    import pymupdf

    with pymupdf.open(stream=io.BytesIO(conteudo), filetype="pdf") as documento:
        paginas = documento.page_count
        registos: List[Dict[str, Any]] = []
        escalao_pdf: Optional[str] = None
        atualizado_em: Optional[str] = None
        vistos: set[str] = set()
        nome_atual: Optional[str] = None
        nif_atual: Optional[str] = None
        pagina_atual: Optional[int] = None

        def fechar() -> None:
            nonlocal nome_atual, nif_atual, pagina_atual
            if nif_atual and nome_atual:
                nome = _limpar_linha(nome_atual)
                # Um NIF/NIPC aparece uma só vez por lista: repetições (o mesmo
                # devedor em duas linhas) não se duplicam no resultado.
                if nome and nif_atual not in vistos:
                    vistos.add(nif_atual)
                    registos.append({"nif": nif_atual, "nome": nome, "pagina": pagina_atual})
            nome_atual = None
            nif_atual = None
            pagina_atual = None

        for indice in range(paginas):
            for bruta in documento[indice].get_text("text").splitlines():
                linha = _limpar_linha(bruta)
                if not linha:
                    continue
                if not escalao_pdf and _ESCALAO_RE.search(linha.lower()):
                    escalao_pdf = linha
                if not atualizado_em:
                    achado_data = _DATA_LISTA_RE.search(unicodedata.normalize("NFKD", linha).lower())
                    if achado_data:
                        atualizado_em = achado_data.group(1)
                if _NIF_RE.match(linha):
                    fechar()
                    nif_atual = linha
                    pagina_atual = indice + 1
                    continue
                if _e_cabecalho(linha):
                    fechar()
                    continue
                if nif_atual is not None:
                    nome_atual = f"{nome_atual} {linha}" if nome_atual else linha

        fechar()

    return {
        "paginas": paginas,
        "registos": registos,
        "escalao_pdf": escalao_pdf,
        "lista_atualizada_em": atualizado_em,
    }


# ---------------------------------------------------------------------------
# Escrita do JSON e indexação
# ---------------------------------------------------------------------------

def write_export(
    spec: Dict[str, Any],
    registos: List[Dict[str, Any]],
    *,
    collected_at: Optional[str] = None,
    pdf: Optional[Dict[str, Any]] = None,
    escalao_pdf: Optional[str] = None,
    lista_atualizada_em: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Grava o JSON de uma lista (um ficheiro por PDF e por data de recolha)."""
    collected_at = collected_at or _now()
    base = f"{Path(str(spec['ficheiro'])).stem}-{collected_at[:10]}"
    caminho = json_dir() / f"{base}.json"
    registos = sorted(registos, key=lambda item: (str(item.get("nome") or ""), str(item.get("nif") or "")))

    payload = {
        "fonte": "financas",
        "entidade": spec.get("entidade") or "financas",
        "entidade_label": ENTIDADES.get(str(spec.get("entidade") or "financas")),
        "ficheiro": spec["ficheiro"],
        "base": base,
        "tipo": spec.get("tipo"),
        "tipo_label": TIPOS_LABEL.get(str(spec.get("tipo"))),
        "escalao": spec.get("escalao"),
        "escalao_pdf": escalao_pdf,
        "valor_min": spec.get("valor_min"),
        "valor_max": spec.get("valor_max"),
        "lista_atualizada_em": lista_atualizada_em or (pdf or {}).get("lista_atualizada_em"),
        "collected_at": collected_at,
        "source_url": f"{BASE_FINANCAS}/{spec['ficheiro']}",
        "pagina_indexacao": PAGINA_INDEXACAO,
        "pdf": pdf,
        "total": len(registos),
        "registos": registos,
        **({"run_id": run_id} if run_id else {}),
    }
    caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    pdf_path = (pdf or {}).get("path")
    return registar_recolha(
        {
            "recolha_id": _recolha_id(str(payload["entidade"]), str(payload["ficheiro"]), collected_at),
            "ficheiro": payload["ficheiro"],
            "base": base,
            "entidade": payload["entidade"],
            "tipo": payload["tipo"],
            "tipo_label": payload["tipo_label"],
            "escalao": payload["escalao"],
            "valor_min": payload["valor_min"],
            "valor_max": payload["valor_max"],
            "lista_atualizada_em": payload["lista_atualizada_em"],
            "collected_at": collected_at,
            "registos": payload["total"],
            "paginas": (pdf or {}).get("paginas"),
            "pdf_bytes": (pdf or {}).get("bytes"),
            "pdf_sha256": (pdf or {}).get("sha256"),
            "pdf_path": pdf_path,
            "json_path": str(caminho),
            "source_url": payload["source_url"],
            "last_modified": (pdf or {}).get("last_modified"),
            "run_id": run_id,
        }
    )


def read_export(base: str) -> Dict[str, Any]:
    """Lê um JSON exportado (por nome base)."""
    caminho = json_dir() / f"{_slug(base)}.json"
    if not caminho.exists():
        raise FileNotFoundError(f"Ficheiro exportado não encontrado: {base}")
    return json.loads(caminho.read_text(encoding="utf-8"))


def _doc_id(entidade: str, ficheiro: str, nif: str) -> str:
    return f"{entidade}:{ficheiro}:{nif}"


def indexar(payload: Dict[str, Any], *, es: Any = None) -> Dict[str, Any]:
    """Indexa um JSON (recém-recolhido ou lido do disco) no Elasticsearch."""
    from api import elasticsearch_client as esc

    cliente = es or esc.get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "indexados": 0}
    esc.ensure_indices(cliente)

    entidade = str(payload.get("entidade") or "financas")
    ficheiro = str(payload.get("ficheiro") or "")
    collected_at = str(payload.get("collected_at") or _now())
    lista_em = payload.get("lista_atualizada_em") or None
    run_id = payload.get("run_id")
    pdf = payload.get("pdf") or {}
    registos = list(payload.get("registos") or [])

    acoes: List[Dict[str, Any]] = []
    for registo in registos:
        nif = str(registo.get("nif") or "").strip()
        nome = str(registo.get("nome") or "").strip()
        if not nif:
            continue
        doc = {
            "doc_id": _doc_id(entidade, ficheiro, nif),
            "nif": nif,
            "nome": nome,
            "entidade": entidade,
            "entidade_label": payload.get("entidade_label") or ENTIDADES.get(entidade),
            "tipo": payload.get("tipo"),
            "tipo_label": payload.get("tipo_label"),
            "escalao": payload.get("escalao"),
            "valor_min": payload.get("valor_min"),
            "valor_max": payload.get("valor_max"),
            "ficheiro": ficheiro,
            "base": payload.get("base"),
            "fonte": payload.get("fonte") or entidade,
            "source_url": payload.get("source_url"),
            "pdf": pdf.get("path") or pdf.get("url"),
            "lista_atualizada_em": lista_em,
            "collected_at": collected_at,
            "pagina": registo.get("pagina"),
            "ingested_at": _now(),
        }
        if run_id:
            doc["run_id"] = run_id
        acoes.append({"_index": esc.DEVEDORES_INDEX, "_id": doc["doc_id"], "_source": doc})

    if acoes:
        from elasticsearch.helpers import bulk

        bulk(cliente, acoes, refresh=True)

    recolha_doc = {
        "recolha_id": payload.get("recolha_id") or _recolha_id(entidade, ficheiro, collected_at),
        "ficheiro": ficheiro,
        "base": payload.get("base"),
        "entidade": entidade,
        "entidade_label": payload.get("entidade_label") or ENTIDADES.get(entidade),
        "tipo": payload.get("tipo"),
        "tipo_label": payload.get("tipo_label"),
        "escalao": payload.get("escalao"),
        "valor_min": payload.get("valor_min"),
        "valor_max": payload.get("valor_max"),
        "lista_atualizada_em": lista_em,
        "collected_at": collected_at,
        "registos": len(registos),
        "paginas": pdf.get("paginas"),
        "pdf_bytes": pdf.get("bytes"),
        "pdf_sha256": pdf.get("sha256"),
        "pdf_path": pdf.get("path"),
        "json_path": payload.get("json_path"),
        "source_url": payload.get("source_url"),
        "last_modified": pdf.get("last_modified"),
        "ingested_at": _now(),
    }
    if run_id:
        recolha_doc["run_id"] = run_id
    cliente.index(index=esc.DEVEDORES_RECOLHAS_INDEX, id=recolha_doc["recolha_id"], document=recolha_doc, refresh=True)

    return {"indexados": len(registos), "ficheiro": ficheiro, "entidade": entidade, "collected_at": collected_at}


def indexar_ficheiros(bases: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Indexa os JSON já exportados (todos ou os indicados)."""
    if bases:
        caminhos = [json_dir() / f"{_slug(base)}.json" for base in bases]
    else:
        caminhos = sorted(json_dir().glob("*.json"))
    resultados: List[Dict[str, Any]] = []
    erros: List[Dict[str, Any]] = []
    total = 0
    for caminho in caminhos:
        if not caminho.exists():
            erros.append({"ficheiro": caminho.name, "error": "não encontrado"})
            continue
        try:
            payload = json.loads(caminho.read_text(encoding="utf-8"))
            resultado = indexar(payload)
            if resultado.get("error"):
                erros.append({"ficheiro": caminho.name, "error": resultado["error"]})
                continue
            total += int(resultado.get("indexados") or 0)
            resultados.append({"ficheiro": caminho.name, **resultado})
        except Exception as exc:  # noqa: BLE001 - um ficheiro mau não trava os restantes
            logger.exception("Falha a indexar %s", caminho)
            erros.append({"ficheiro": caminho.name, "error": str(exc)})
    return {"ficheiros": len(resultados), "registos": total, "items": resultados, "errors": erros}


# ---------------------------------------------------------------------------
# Recolha (Finanças e Segurança Social)
# ---------------------------------------------------------------------------

def recolher_financas(
    ficheiros: Optional[Iterable[str]] = None,
    *,
    forcar: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Recolhe os PDF das Finanças e grava PDF + JSON + índice (por ficheiro)."""
    pedidos = {str(nome).strip().lower() for nome in ficheiros or [] if str(nome).strip()}
    specs = [spec for spec in FICHEIROS_FINANCAS if not pedidos or str(spec["ficheiro"]).lower() in pedidos]
    if not specs:
        return {"error": "Nenhum ficheiro das Finanças corresponde ao pedido.", "items": []}

    manifest = read_manifest().get("recolhas") or {}
    # As listas das Finanças são atualizadas **diariamente** (saídas por pagamento
    # e entradas mensais), por isso «já recolhido» só vale para o próprio dia: uma
    # nova recolha no dia seguinte trás a lista atualizada, sem repetir o trabalho
    # se já se recolheu hoje.
    hoje = _hoje()
    ja_tem = {
        str(item.get("ficheiro"))
        for item in manifest.values()
        if str(item.get("entidade")) == "financas"
        and item.get("registos")
        and str(item.get("collected_at") or "")[:10] == hoje
    }

    resultados: List[Dict[str, Any]] = []
    erros: List[Dict[str, Any]] = []
    total_registos = 0
    total_novos = 0

    for numero, spec in enumerate(specs, start=1):
        ficheiro = str(spec["ficheiro"])
        if progresso is not None:
            progresso["current"] = {"ficheiro": ficheiro, "escalao": spec.get("escalao")}
            progresso["ficheiros_done"] = numero - 1
            progresso["phase"] = f"a recolher {ficheiro}"
        if ficheiro in ja_tem and not forcar:
            resultados.append({"ficheiro": ficheiro, "saltado": True, "motivo": "já recolhido"})
            continue
        url = f"{BASE_FINANCAS}/{ficheiro}"
        try:
            conteudo, cabecalhos = descarregar_pdf(url)
            analise = parse_pdf(conteudo, spec)
            recolhido_em = _now()
            destino = pdf_dir() / f"{Path(ficheiro).stem}-{recolhido_em[:10]}.pdf"
            destino.write_bytes(conteudo)
            info_pdf = {
                "path": str(destino),
                "url": url,
                "bytes": len(conteudo),
                "sha256": hashlib.sha256(conteudo).hexdigest(),
                "paginas": analise["paginas"],
                "last_modified": cabecalhos.get("last-modified"),
                "recolhido_em": recolhido_em,
                "lista_atualizada_em": analise.get("lista_atualizada_em"),
            }
            entrada = write_export(
                {**spec, "entidade": "financas"},
                analise["registos"],
                collected_at=recolhido_em,
                pdf=info_pdf,
                escalao_pdf=analise.get("escalao_pdf"),
                lista_atualizada_em=analise.get("lista_atualizada_em"),
                run_id=run_id,
            )
            indice = indexar(
                {
                    **read_export(str(entrada["base"])),
                    "recolha_id": entrada["recolha_id"],
                    "json_path": entrada["json_path"],
                    "run_id": run_id,
                }
            )
            total_registos += len(analise["registos"])
            if ficheiro not in ja_tem:
                total_novos += 1
            resultados.append(
                {
                    "ficheiro": ficheiro,
                    "entidade": "financas",
                    "tipo": spec["tipo"],
                    "escalao": spec["escalao"],
                    "registos": len(analise["registos"]),
                    "paginas": analise["paginas"],
                    "pdf": str(destino),
                    "json": entrada["json_path"],
                    "collected_at": recolhido_em,
                    "lista_atualizada_em": analise.get("lista_atualizada_em"),
                    "indexados": indice.get("indexados"),
                }
            )
            logger.info("Devedores: %s recolhido (%s registos)", ficheiro, len(analise["registos"]))
        except Exception as exc:  # noqa: BLE001 - um ficheiro mau não trava os restantes
            logger.exception("Falha a recolher %s", ficheiro)
            erros.append({"ficheiro": ficheiro, "error": f"{type(exc).__name__}: {exc}"})
        if progresso is not None:
            progresso["registos"] = total_registos

    if progresso is not None:
        progresso["ficheiros_done"] = len(specs)
        progresso["current"] = None

    return {
        "entidade": "financas",
        "ficheiros": len(specs),
        "ficheiros_novos": total_novos,
        "registos": total_registos,
        "items": resultados,
        "errors": erros,
    }


def recolher_seguranca_social(
    *,
    escaloes: Optional[Iterable[str]] = None,
    tipos: Optional[Iterable[str]] = None,
    max_paginas: int = 400,
    progresso: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Recolha (experimental) da lista da Segurança Social.

    A aplicação da Segurança Social recusa clientes não-interactivos, pelo que
    esta função corre um browser real (Playwright, já disponível no ambiente) e
    faz os pedidos **dentro da página** (mesma sessão). Se a fonte recusar o
    acesso, devolve `error` com a explicação — os dados podem sempre entrar pelo
    JSON importado.
    """
    from api import elasticsearch_client as esc

    cliente = esc.get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "items": []}
    esc.ensure_indices(cliente)

    escolhidos_tipos = {str(t) for t in tipos or []} or {str(item["tipo"]) for item in TIPOS_SS}
    escolhidos_escaloes = {str(e) for e in escaloes or []} or {str(item["escalao"]) for item in ESCALOES_SS}

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Playwright indisponível para recolher a Segurança Social: {exc}", "items": []}

    resultados: List[Dict[str, Any]] = []
    erros: List[Dict[str, Any]] = []
    total = 0

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page(locale="pt-PT")
        try:
            pagina.goto(SS_URL, wait_until="domcontentloaded", timeout=120000)
            if "errors/404" in pagina.url or not pagina.evaluate(
                "!!document.querySelector('form#sefFormConsultaListaDevedores')"
            ):
                raise RuntimeError(
                    "A Segurança Social recusou o acesso automático (página 404). "
                    "Use a importação do JSON ou recolha esta lista manualmente."
                )
        except Exception as exc:  # noqa: BLE001
            navegador.close()
            return {"error": f"{type(exc).__name__}: {exc}", "items": []}

        for tipo_spec in TIPOS_SS:
            if str(tipo_spec["tipo"]) not in escolhidos_tipos:
                continue
            for escalao_spec in ESCALOES_SS:
                if str(escalao_spec["escalao"]) not in escolhidos_escaloes:
                    continue
                if progresso is not None:
                    progresso["phase"] = f"SS {tipo_spec['tipo']} · {escalao_spec['escalao']}"
                registos: List[Dict[str, Any]] = []
                for numero in range(max_paginas):
                    try:
                        linhas = pagina.evaluate(
                            _JS_PAGINA_SS,
                            [numero * 50, str(tipo_spec["chave"]), str(escalao_spec["chave"]), "", ""],
                        )
                    except Exception as exc:  # noqa: BLE001
                        erros.append({"tipo": tipo_spec["tipo"], "escalao": escalao_spec["escalao"], "error": str(exc)})
                        break
                    if not linhas:
                        break
                    registos.extend(linhas)
                if not registos:
                    continue
                recolhido_em = _now()
                spec = {
                    "ficheiro": f"seg-social-{tipo_spec['tipo']}-{_slug(escalao_spec['escalao'])}.json",
                    "entidade": "seguranca_social",
                    "tipo": tipo_spec["tipo"],
                    "tipo_label": TIPOS_LABEL.get(tipo_spec["tipo"], tipo_spec["tipo"]),
                    "escalao": escalao_spec["escalao"],
                    "valor_min": escalao_spec["valor_min"],
                    "valor_max": escalao_spec["valor_max"],
                }
                entrada = write_export(spec, registos, collected_at=recolhido_em, run_id=run_id)
                payload = read_export(str(entrada["base"]))
                payload.update({"recolha_id": entrada["recolha_id"], "json_path": entrada["json_path"], "source_url": SS_URL})
                indice = indexar(payload, es=cliente)
                total += len(registos)
                resultados.append(
                    {
                        **spec,
                        "registos": len(registos),
                        "collected_at": recolhido_em,
                        "json": entrada["json_path"],
                        "indexados": indice.get("indexados"),
                    }
                )
        navegador.close()

    if progresso is not None:
        progresso["registos"] = total
        progresso["current"] = None
    return {"entidade": "seguranca_social", "registos": total, "items": resultados, "errors": erros}


#: Pedido de uma página da lista da Segurança Social, feito **na própria página**
#: (mesma sessão do browser e mesmo `ViewState` do formulário JSF).
_JS_PAGINA_SS = r"""
async ([primeiro, tipo, escalao, nome, nif]) => {
  const FORM = 'sefFormConsultaListaDevedores';
  const TAB = FORM + ':sefConsultaListaDevedoresTabela';
  const val = (n) => { const el = document.querySelector('[name="' + n + '"]'); return el ? el.value : ''; };
  const params = new URLSearchParams();
  params.set('javax.faces.partial.ajax', 'true');
  params.set('javax.faces.source', TAB);
  params.set('javax.faces.partial.execute', TAB);
  params.set('javax.faces.partial.render', TAB);
  params.set('javax.faces.behavior.event', 'page');
  params.set('javax.faces.partial.event', 'page');
  params.set(TAB + '_pagination', 'true');
  params.set(TAB + '_first', String(primeiro));
  params.set(TAB + '_rows', '50');
  params.set(TAB + '_skipChildren', 'true');
  params.set(TAB + '_encodeFeature', 'true');
  params.set(FORM, FORM);
  params.set(FORM + ':sefConsultaListaDevedoresSelectTipoEntidade_input', tipo);
  params.set(FORM + ':sefConsultaListaDevedoresSelectEscaloes_input', escalao);
  params.set(FORM + ':sefConsultaListaDevedoresInputNome', nome);
  params.set(FORM + ':sefConsultaListaDevedoresInputNIF', nif);
  params.set(TAB + '_rppDD', '50');
  params.set('CTKN_DYN', val('CTKN_DYN'));
  params.set('x-lsu', '/home');
  params.set('x-lbu', '/ptss/sef/lista-de-devedores/consulta-lista-de-devedores');
  params.set('javax.faces.ViewState', val('javax.faces.ViewState'));
  const r = await fetch(location.pathname + location.search, {
    method: 'POST',
    headers: {
      'Faces-Request': 'partial/ajax',
      'X-Requested-With': 'XMLHttpRequest',
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    },
    body: params.toString(),
  });
  if (!r.ok) { return []; }
  const texto = await r.text();
  const doc = new DOMParser().parseFromString(texto, 'text/xml');
  return [...doc.querySelectorAll('tr[data-ri]')]
    .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))
    .filter(celulas => celulas.length >= 2 && celulas[1])
    .map(celulas => ({ nif: celulas[1], nome: celulas[0] }));
}
"""


# ---------------------------------------------------------------------------
# Pesquisa
# ---------------------------------------------------------------------------

def _folding(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower().strip()


def search(
    q: Optional[str] = None,
    *,
    nif: Optional[str] = None,
    entidade: Optional[str] = None,
    tipo: Optional[str] = None,
    escalao: Optional[List[str]] = None,
    valor_minimo: Optional[float] = None,
    ficheiro: Optional[str] = None,
    lista_atualizada_em: Optional[str] = None,
    collected_from: Optional[str] = None,
    collected_to: Optional[str] = None,
    sort: str = "relevancia",
    order: str = "desc",
    page: int = 1,
    size: int = 25,
    es: Any = None,
) -> Dict[str, Any]:
    """Pesquisa os devedores indexados, com facetas e KPIs."""
    from api import elasticsearch_client as esc

    cliente = es or esc.get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}, "kpis": {}}
    esc.ensure_indices(cliente)

    filtros: List[Dict[str, Any]] = []
    must: List[Dict[str, Any]] = []

    termo = (q or "").strip()
    nif_limpo = re.sub(r"\D", "", nif or "")
    if nif_limpo:
        filtros.append({"term": {"nif": nif_limpo}})
    if termo:
        if re.fullmatch(r"\d{9}", re.sub(r"\D", "", termo)):
            filtros.append({"term": {"nif": re.sub(r"\D", "", termo)}})
        else:
            must.append(
                {
                    "multi_match": {
                        "query": termo,
                        "fields": ["nome^3", "nome.keyword"],
                        "type": "best_fields",
                        "operator": "and",
                    }
                }
            )
    if entidade:
        filtros.append({"term": {"entidade": entidade}})
    if tipo:
        filtros.append({"term": {"tipo": tipo}})
    if escalao:
        filtros.append({"terms": {"escalao": list(escalao)}})
    if ficheiro:
        filtros.append({"term": {"ficheiro": ficheiro}})
    if valor_minimo is not None:
        filtros.append({"range": {"valor_min": {"gte": float(valor_minimo)}}})
    if lista_atualizada_em:
        filtros.append({"term": {"lista_atualizada_em": lista_atualizada_em}})
    if collected_from or collected_to:
        intervalo: Dict[str, Any] = {}
        if collected_from:
            intervalo["gte"] = collected_from
        if collected_to:
            intervalo["lte"] = collected_to
        filtros.append({"range": {"collected_at": intervalo}})

    query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}], "filter": filtros}}

    ordenacoes = {
        "relevancia": [{"_score": "desc"}, {"nome.keyword": "asc"}],
        "nome": [{"nome.keyword": order}],
        "escalao": [{"valor_min": order}, {"nome.keyword": "asc"}],
        "recolha": [{"collected_at": order}, {"nome.keyword": "asc"}],
        "lista": [{"lista_atualizada_em": order}, {"nome.keyword": "asc"}],
    }
    ordenar = ordenacoes.get(sort) or ordenacoes["relevancia"]

    corpo = {
        "query": query,
        "from": max(0, (page - 1) * size),
        "size": size,
        "sort": ordenar,
        "track_total_hits": True,
        "aggs": {
            "tipo": {"terms": {"field": "tipo", "size": 5}},
            "entidade": {"terms": {"field": "entidade", "size": 5}},
            "escalao": {"terms": {"field": "escalao", "size": 20, "order": {"min_valor": "asc"}}, "aggs": {"min_valor": {"min": {"field": "valor_min"}}}},
            "ficheiro": {"terms": {"field": "ficheiro", "size": 30}},
            "lista": {"terms": {"field": "lista_atualizada_em", "size": 10, "order": {"_key": "desc"}}},
            "recolha": {"terms": {"field": "collected_at", "size": 10, "order": {"_key": "desc"}}},
            "ficheiros_distintos": {"cardinality": {"field": "ficheiro"}},
            "sem_duplicados": {"cardinality": {"field": "nif"}},
        },
    }

    try:
        resposta = cliente.search(index=esc.DEVEDORES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pesquisa de devedores falhou")
        return {"error": str(exc), "total": 0, "items": [], "facets": {}, "kpis": {}}

    def _buckets(nome: str) -> List[Dict[str, Any]]:
        return [
            {"key": bucket.get("key"), "count": bucket.get("doc_count")}
            for bucket in ((resposta.get("aggregations") or {}).get(nome) or {}).get("buckets", [])
        ]

    itens = []
    for hit in resposta.get("hits", {}).get("hits", []):
        fonte = hit.get("_source") or {}
        itens.append({**fonte, "score": hit.get("_score")})

    agregacoes = resposta.get("aggregations") or {}
    total = (resposta.get("hits", {}).get("total") or {}).get("value", 0)

    def _data_mais_recente(nome_agg: str) -> Optional[str]:
        """Data (AAA-MM-DD) da entrada mais recente de uma agregação por data."""
        buckets = _buckets(nome_agg)
        if not buckets or buckets[0].get("key") is None:
            return None
        chave = buckets[0]["key"]
        if isinstance(chave, (int, float)):
            return datetime.fromtimestamp(float(chave) / 1000, tz=timezone.utc).date().isoformat()
        return str(chave)[:10]

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": itens,
        "facets": {
            "tipo": _buckets("tipo"),
            "entidade": _buckets("entidade"),
            "escalao": [
                {**_buckets("escalao")[i], "valor_min": bucket.get("min_valor", {}).get("value")}
                for i, bucket in enumerate((agregacoes.get("escalao") or {}).get("buckets", []))
            ],
            "ficheiro": _buckets("ficheiro"),
            "lista_atualizada_em": [
                {**bucket, "key": datetime.fromtimestamp(float(bucket["key"]) / 1000, tz=timezone.utc).date().isoformat()}
                if isinstance(bucket.get("key"), (int, float))
                else bucket
                for bucket in _buckets("lista")
            ],
            "collected_at": [
                {**bucket, "key": datetime.fromtimestamp(float(bucket["key"]) / 1000, tz=timezone.utc).date().isoformat()}
                if isinstance(bucket.get("key"), (int, float))
                else bucket
                for bucket in _buckets("recolha")
            ],
        },
        "kpis": {
            "registos": total,
            "devedores_distintos": (agregacoes.get("sem_duplicados") or {}).get("value", 0),
            "ficheiros": (agregacoes.get("ficheiros_distintos") or {}).get("value", 0),
            "singulares": next((item["count"] for item in _buckets("tipo") if item["key"] == "singulares"), 0),
            "coletivos": next((item["count"] for item in _buckets("tipo") if item["key"] == "coletivos"), 0),
            "financas": next((item["count"] for item in _buckets("entidade") if item["key"] == "financas"), 0),
            "seguranca_social": next(
                (item["count"] for item in _buckets("entidade") if item["key"] == "seguranca_social"), 0
            ),
            "ultima_lista": _data_mais_recente("lista"),
            "ultima_recolha": _data_mais_recente("recolha"),
        },
    }


def por_nif(nif: str, *, es: Any = None) -> Dict[str, Any]:
    """Registos de um NIF/NIPC em todas as listas (Finanças e Segurança Social)."""
    from api import elasticsearch_client as esc

    limpo = re.sub(r"\D", "", str(nif or ""))
    if not limpo:
        return {"nif": "", "total": 0, "items": [], "source": "none"}
    cliente = es or esc.get_es_client()
    if not cliente:
        return {"nif": limpo, "total": 0, "items": [], "devedor": False, "error": "Elasticsearch indisponível"}

    resposta = search(nif=limpo, size=50, sort="escalao", order="desc", es=cliente)
    if resposta.get("error"):
        return {"nif": limpo, "total": 0, "items": [], "devedor": False, "error": resposta["error"]}

    itens = resposta.get("items") or []
    escaloes = [item.get("escalao") for item in itens if item.get("escalao")]
    entidades = sorted({str(item.get("entidade")) for item in itens if item.get("entidade")})
    return {
        "nif": limpo,
        "nome": next((item.get("nome") for item in itens if item.get("nome")), None),
        "total": resposta.get("total", 0),
        "entidades": entidades,
        "escaloes": escaloes,
        "maior_valor_min": max((item.get("valor_min") or 0 for item in itens), default=None),
        "devedor": bool(itens),
        "items": itens,
        "source": "index",
    }


# ---------------------------------------------------------------------------
# Trabalhos (recolha em segundo plano)
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
    """Arranca uma recolha de devedores em segundo plano."""
    with _JOBS_LOCK:
        a_correr = [job for job in _JOBS.values() if job.get("status") == _RUNNING]
        if a_correr:
            return {
                "job_id": a_correr[0]["job_id"],
                "status": _RUNNING,
                "already_running": True,
                "message": "Já existe uma recolha de devedores a correr.",
            }
        job: Dict[str, Any] = {
            "job_id": uuid.uuid4().hex[:12],
            "status": _RUNNING,
            "started_at": _now(),
            "finished_at": None,
            "payload": payload,
            "progress": {
                "phase": "a começar",
                "ficheiros_done": 0,
                "registos": 0,
                "current": None,
            },
            "result": None,
            "error": None,
        }
        _JOBS[job["job_id"]] = job
        _prune_jobs()

    threading.Thread(target=_run_job, args=(job,), name="devedores-recolha", daemon=True).start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    try:
        _run_job_inner(job)
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Recolha de devedores falhou")
        job["status"] = "error"
        job["finished_at"] = _now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["progress"]["phase"] = "erro"
        job["progress"]["current"] = None


def _run_job_inner(job: Dict[str, Any]) -> None:
    payload = job["payload"]
    progresso = job["progress"]
    run_id = job["job_id"]
    entidades = {str(item) for item in (payload.get("entidades") or ["financas"])}
    ficheiros = payload.get("ficheiros")
    forcar = bool(payload.get("forcar"))

    resultado: Dict[str, Any] = {"entidades": {}, "errors": []}
    if "financas" in entidades:
        progresso["phase"] = "a recolher as listas das Finanças"
        resultado["entidades"]["financas"] = recolher_financas(
            ficheiros, forcar=forcar, progresso=progresso, run_id=run_id
        )
    if "seguranca_social" in entidades:
        progresso["phase"] = "a recolher a lista da Segurança Social"
        resultado["entidades"]["seguranca_social"] = recolher_seguranca_social(
            escaloes=payload.get("escaloes_ss"),
            tipos=payload.get("tipos_ss"),
            max_paginas=int(payload.get("max_paginas") or 400),
            progresso=progresso,
            run_id=run_id,
        )

    registos = sum(int((valor or {}).get("registos") or 0) for valor in resultado["entidades"].values())
    erros = [erro for valor in resultado["entidades"].values() for erro in ((valor or {}).get("errors") or [])]
    falhas = [valor.get("error") for valor in resultado["entidades"].values() if (valor or {}).get("error")]
    resultado.update({"registos": registos, "errors": erros, "falhas": [f for f in falhas if f]})

    job["result"] = resultado
    job["status"] = "error" if falhas and not registos else "done"
    job["finished_at"] = _now()
    if falhas:
        job["error"] = "; ".join(falhas)
    progresso["phase"] = "concluído" if job["status"] == "done" else "concluído com avisos"
    progresso["registos"] = registos
    progresso["current"] = None


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


# ---------------------------------------------------------------------------
# Metadados
# ---------------------------------------------------------------------------

def meta() -> Dict[str, Any]:
    """Metadados do módulo: pasta, índice e volumetria recolhida."""
    from api import elasticsearch_client as esc

    recolhas = list_recolhas()
    resumo_indice: Dict[str, Any] = {}
    cliente = esc.get_es_client()
    if cliente:
        try:
            if cliente.indices.exists(index=esc.DEVEDORES_INDEX):
                contagem = cliente.count(index=esc.DEVEDORES_INDEX)
                resumo_indice = {
                    "index": esc.DEVEDORES_INDEX,
                    "registos": contagem.get("count", 0),
                    "recolhas_index": esc.DEVEDORES_RECOLHAS_INDEX,
                }
        except Exception as exc:  # noqa: BLE001
            resumo_indice = {"error": str(exc)}
    return {
        "module": "devedores",
        "export_dir": recolhas["dir"],
        "export_dir_env": EXPORT_DIR_ENV,
        "pdf_dir": str(pdf_dir()),
        "json_dir": str(json_dir()),
        "index": esc.DEVEDORES_INDEX,
        "indice": resumo_indice,
        "recolhas": recolhas["total"],
        "ficheiros": len({str(item.get("ficheiro")) for item in recolhas["items"]}),
        "registos_recolhidos": recolhas["registos"],
        "ultima_recolha": (recolhas["items"][0]["collected_at"] if recolhas["items"] else None),
        "fontes": {"financas": len(FICHEIROS_FINANCAS), "seguranca_social": len(ESCALOES_SS) * len(TIPOS_SS)},
        "notes": (
            "Listas públicas de devedores. Das Finanças são recolhidos os 12 PDF oficiais "
            "(singulares e coletivos por escalão), guardando o PDF, um JSON por ficheiro com a data da "
            "recolha e os registos indexados em `finance_devedores`. A lista da Segurança Social é uma "
            "consulta interactiva que recusa pedidos automáticos (recolha experimental)."
        ),
    }
