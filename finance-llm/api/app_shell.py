"""Cabeçalho e rodapé das páginas públicas da plataforma.

Quem chega ao IQ OS sem sessão vê as páginas de **entrada** (`/`, `/login` e
`/register`). Ao contrário do site público do CMS (`/site/...`), que tem a sua
própria navegação, estas páginas são a montra da **plataforma**: levam o
logótipo, a navegação e os contactos que a casa quer mostrar a quem ainda não
entrou.

Essa configuração é **independente** da do site (um cabeçalho para a plataforma,
outro para o site) e vive num documento JSON próprio
(`data/app/shell.json`), editado no backoffice (Administração → **Plataforma**).
O ficheiro é a fonte de verdade e pode ser versionado, como o do CMS.

Regras de leitura, para o painel poder limpar campos sem partir a página:

* campo **ausente** → volta a predefinição (o cabeçalho nunca fica sem marca);
* campo **presente e vazio** → fica mesmo vazio (o cabeçalho fica sem esse link,
  sem a frase de topo ou sem uma rede social).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SHELL_DIR = ROOT / "data" / "app"
SHELL_PATH = SHELL_DIR / "shell.json"
SHELL_VERSION = 1

#: Limites do que se aceita. A navegação é uma fila de pastilhas: a partir de
#: duas dezenas de entradas deixa de se ler como navegação e passa a ser uma
#: lista de links.
MAX_LINKS = 12
MAX_LABEL = 40
MAX_HREF = 300
MAX_TEXT = 240

#: Redes sociais do rodapé, pela ordem em que aparecem.
SOCIAL: Tuple[Tuple[str, str], ...] = (
    ("email", "Email"),
    ("linkedin", "LinkedIn"),
    ("x", "X"),
    ("github", "GitHub"),
)

#: Predefinições: o que as páginas de entrada mostram enquanto ninguém alterar
#: nada no backoffice. São também o ponto de partida do painel.
DEFAULTS: Dict[str, Any] = {
    "brand": {
        "name": "IQ OS",
        "tagline": "Plataforma de inteligência financeira",
        "logo_url": "",
        "logo_alt": "",
    },
    "header": {
        "items": [],
        "cta": {"label": "Criar conta", "href": "/register"},
        "secondary": {"label": "Entrar", "href": "/login"},
    },
    "footer": {
        "text": "Sabemos Studio · IQ OS — Plataforma de Inteligência Financeira",
        "items": [
            {"label": "Entrar", "href": "/login"},
            {"label": "Criar conta", "href": "/register"},
        ],
        "social": {chave: "" for chave, _ in SOCIAL},
    },
}

#: Endereços aceites: caminhos do próprio sítio (`/site/blog`) e esquemas que um
#: link de cabeçalho pode usar. `javascript:` e companhia ficam de fora — o valor
#: vem da base de dados e é escrito no HTML (`href`).
_HREF_RE = re.compile(r"^(?:/|https?://|mailto:|tel:)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_lock = threading.RLock()


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    """Texto de uma linha: sem espaços a mais, cortado no limite."""
    texto = " ".join(str(value or "").split())
    return texto[:limit].strip()


def _href(value: Any) -> str:
    """Endereço aceite para um link (vazio quando não serve)."""
    if not isinstance(value, str):
        return ""
    endereco = value.strip()[:MAX_HREF]
    if not endereco or not _HREF_RE.match(endereco):
        return ""
    return endereco


def _link(value: Any) -> Optional[Dict[str, str]]:
    """Link (`label` + `href`) ou `None` quando falta uma das partes."""
    if not isinstance(value, dict):
        return None
    etiqueta = _text(value.get("label"), MAX_LABEL)
    endereco = _href(value.get("href"))
    if not etiqueta or not endereco:
        return None
    return {"label": etiqueta, "href": endereco}


def _links(value: Any) -> List[Dict[str, str]]:
    """Lista de links válidos, sem repetições de endereço e dentro do limite."""
    if not isinstance(value, (list, tuple)):
        return []
    itens: List[Dict[str, str]] = []
    vistos: List[str] = []
    for entrada in value:
        link = _link(entrada)
        if link is None or link["href"] in vistos:
            continue
        vistos.append(link["href"])
        itens.append(link)
        if len(itens) >= MAX_LINKS:
            break
    return itens


def _social_href(chave: str, valor: str) -> str:
    """Endereço de uma rede social: um email sem esquema ganha `mailto:`.

    Um valor que já traz esquema (ou um caminho do próprio sítio) é respeitado —
    `mailto:mailto:…` era o que saía de um email colado com o esquema à frente.
    """
    if _href(valor):
        return valor
    if chave == "email" and _EMAIL_RE.match(valor):
        return f"mailto:{valor}"
    return ""


# --------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------
def _clean_brand(value: Any) -> Dict[str, str]:
    origem = value if isinstance(value, dict) else {}
    nome = _text(origem.get("name"), MAX_LABEL) or str(DEFAULTS["brand"]["name"])
    # A frase de topo segue a mesma regra das secções: sem a chave vale a
    # predefinição, com a chave e vazia fica mesmo vazia (o cabeçalho sem frase).
    frase = _text(origem.get("tagline"), MAX_TEXT) if "tagline" in origem else str(DEFAULTS["brand"]["tagline"])
    return {
        "name": nome,
        "tagline": frase,
        "logo_url": _href(origem.get("logo_url")),
        "logo_alt": _text(origem.get("logo_alt"), MAX_LABEL),
    }


def _clean_items(value: Any, predefinicao: Any) -> List[Dict[str, str]]:
    """Lista de links de uma secção.

    Sem a chave, vale a predefinição; com a chave e vazia, fica vazia (é assim
    que o painel tira todos os links sem perder o resto).
    """
    origem = value if isinstance(value, dict) else {}
    if "items" in origem:
        return _links(origem.get("items"))
    return copy.deepcopy(list(predefinicao or []))


def _clean_header(value: Any) -> Dict[str, Any]:
    """Cabeçalho: navegação e os dois botões (principal e secundário)."""
    origem = value if isinstance(value, dict) else {}
    resultado: Dict[str, Any] = {"items": _clean_items(value, DEFAULTS["header"]["items"])}
    for chave in ("cta", "secondary"):
        if chave not in origem:
            resultado[chave] = copy.deepcopy(DEFAULTS["header"].get(chave))
            continue
        # Presente e vazio (ou inválido) tira o botão do cabeçalho.
        resultado[chave] = _link(origem.get(chave))
    return resultado


def _clean_footer(value: Any) -> Dict[str, Any]:
    """Rodapé: ligações, frase e redes sociais."""
    origem = value if isinstance(value, dict) else {}
    rodape = {"items": _clean_items(value, DEFAULTS["footer"]["items"])}
    rodape.update(_clean_footer_extra(origem))
    return rodape


def _clean_footer_extra(value: Any) -> Dict[str, Any]:
    """Texto e redes sociais do rodapé (a lista de links vem de `_clean_items`)."""
    origem = value if isinstance(value, dict) else {}
    texto = _text(origem.get("text"), MAX_TEXT) if "text" in origem else str(DEFAULTS["footer"]["text"])
    sociais_origem = origem.get("social") if isinstance(origem.get("social"), dict) else {}
    sociais: Dict[str, str] = {}
    for chave, _ in SOCIAL:
        if chave in sociais_origem:
            sociais[chave] = _text(sociais_origem.get(chave), MAX_HREF)
        else:
            sociais[chave] = str((DEFAULTS["footer"]["social"] or {}).get(chave) or "")
    return {"text": texto, "social": sociais}


def _clean(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Documento completo a partir do que o painel enviou (predefinições à mistura)."""
    origem = payload if isinstance(payload, dict) else {}
    return {
        "version": SHELL_VERSION,
        "brand": _clean_brand(origem.get("brand")),
        "header": _clean_header(origem.get("header")),
        "footer": _clean_footer(origem.get("footer")),
    }


# --------------------------------------------------------------------------
# Ler/gravar
# --------------------------------------------------------------------------
def _load_raw() -> Dict[str, Any]:
    """Documento tal como está no disco (vazio quando ainda não existe).

    Lê-se com `utf-8-sig`: um BOM (é o que um editor de Windows põe num ficheiro
    gravado como «UTF-8 com BOM») não pode fazer a configuração cair nas
    predefinições sem ninguém perceber porquê.
    """
    try:
        with SHELL_PATH.open(encoding="utf-8-sig") as ficheiro:
            dados = json.load(ficheiro)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        # Um ficheiro estragado não pode derrubar as páginas de entrada: volta-se
        # às predefinições e fica o aviso no registo.
        logger.warning("Shell da plataforma ilegível (%s): %s", SHELL_PATH, exc)
        return {}
    return dados if isinstance(dados, dict) else {}


def document() -> Dict[str, Any]:
    """Configuração em vigor (com predefinições), para o backoffice editar."""
    dados = _load_raw()
    limpo = _clean(dados)
    limpo["updated_at"] = str(dados.get("updated_at") or "")
    limpo["updated_by"] = str(dados.get("updated_by") or "")
    limpo["configured"] = bool(dados)
    return limpo


def public_payload() -> Dict[str, Any]:
    """O que as páginas públicas consomem: tudo resolvido, nada a interpretar."""
    dados = document()
    marca = dados["brand"]
    rodape = dados["footer"]
    sociais: List[Dict[str, str]] = []
    for chave, etiqueta in SOCIAL:
        valor = str((rodape.get("social") or {}).get(chave) or "")
        endereco = _social_href(chave, valor)
        if endereco:
            sociais.append({"key": chave, "label": etiqueta, "href": endereco})
    return {
        "brand": {
            "name": marca["name"],
            "tagline": marca["tagline"],
            "logo_url": marca["logo_url"],
            "logo_alt": marca["logo_alt"] or marca["name"],
        },
        "header": {
            "items": dados["header"]["items"],
            "cta": dados["header"]["cta"],
            "secondary": dados["header"]["secondary"],
        },
        "footer": {"text": rodape["text"], "items": rodape["items"], "social": sociais},
        "updated_at": dados["updated_at"],
    }


def save(payload: Optional[Dict[str, Any]], author: str = "") -> Dict[str, Any]:
    """Grava a configuração (escrita atómica) e devolve o documento em vigor."""
    limpo = _clean(payload)
    limpo["updated_at"] = _now()
    limpo["updated_by"] = _text(author, MAX_LABEL)
    with _lock:
        SHELL_DIR.mkdir(parents=True, exist_ok=True)
        temporario = SHELL_PATH.with_suffix(".json.tmp")
        with temporario.open("w", encoding="utf-8") as ficheiro:
            json.dump(limpo, ficheiro, ensure_ascii=False, indent=2)
            ficheiro.write("\n")
        os.replace(temporario, SHELL_PATH)
    return limpo


def defaults() -> Dict[str, Any]:
    """Predefinições (para o painel as poder repor)."""
    return copy.deepcopy(DEFAULTS)
