"""Catálogo CAE-Rev.4 com descrições.

O ficheiro `data/docs/CAE-Rev.4.md` é convertido para uma lista indexada de
entradas `{code, name, level, section, path}`. A lista é mantida em cache para
servir o endpoint `/cae/list` sem recarregar o markdown em cada pedido.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Regex da estrutura markdown do CAE-Rev.4
RE_SECCAO = re.compile(r"^## Secção ([A-Z]) — (.*)$")
RE_DIVISAO = re.compile(r"^### Divisão (\d{2}) — (.*)$")
RE_GRUPO = re.compile(r"^#### Grupo (\d{3}) — (.*)$")
RE_CLASSE_SUB = re.compile(r"^##### Classe (\d{4}) \(subclasse (\d{5})\) — (.*)$")
RE_CLASSE = re.compile(r"^##### Classe (\d{4}) — (.*)$")
RE_SUBCLASSE = re.compile(r"^- \*\*(\d{5})\*\* — (.*)$")


class CaeCatalog:
    """Catálogo CAE carregado a partir do markdown padrão do projeto."""

    def __init__(self, entries: List[Dict[str, Any]]) -> None:
        self.entries = entries
        self._by_code: Dict[str, List[Dict[str, Any]]] = {}
        for entry in entries:
            self._by_code.setdefault(entry["code"], []).append(entry)

    def find(self, code: str) -> Optional[Dict[str, Any]]:
        """Devolve a primeira entrada que corresponde ao código exato."""
        matches = self._by_code.get(code.strip())
        return matches[0] if matches else None

    def search(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Pesquisa por código ou texto (insensível a maiúsculas e acentos leves)."""
        term = _normalize(query)
        results: List[Dict[str, Any]] = []
        for entry in self.entries:
            if term in _normalize(entry["code"]) or term in _normalize(entry["name"]):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def codes(self) -> List[str]:
        """Todos os códigos distintos."""
        return list(self._by_code.keys())


def _normalize(text: str) -> str:
    """Normalização mínima para pesquisa textual."""
    return (
        text.lower()
        .replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ì", "i")
        .replace("ó", "o")
        .replace("ò", "o")
        .replace("õ", "o")
        .replace("ô", "o")
        .replace("ú", "u")
        .replace("ù", "u")
        .replace("ç", "c")
        .replace("ñ", "n")
    )


def _default_markdown_path() -> Path:
    """Descobre o ficheiro CAE-Rev.4.md no data/docs do projeto."""
    candidates = [
        Path(__file__).resolve().parent.parent / "data" / "docs" / "CAE-Rev.4.md",
        Path(__file__).resolve().parent.parent.parent / "data" / "docs" / "CAE-Rev.4.md",
        Path.cwd() / "data" / "docs" / "CAE-Rev.4.md",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("CAE-Rev.4.md não encontrado em data/docs")


# Cache global carregado lazy.
_catalog_cache: Optional[CaeCatalog] = None


def load_cae_catalog(path: Optional[Path] = None) -> CaeCatalog:
    """Carrega (com cache) o catálogo CAE a partir do markdown."""
    global _catalog_cache
    if _catalog_cache is not None and path is None:
        return _catalog_cache

    md_path = path or _default_markdown_path()
    text = md_path.read_text(encoding="utf-8")

    entries: List[Dict[str, Any]] = []
    atual_seccao = ""
    atual_divisao = ""
    atual_grupo = ""

    for linha in text.split("\n"):
        linha = linha.rstrip()
        m: Optional[re.Match[str]] = None
        if (m := RE_SECCAO.match(linha)) is not None:
            atual_seccao = m.group(1)
            atual_divisao = ""
            atual_grupo = ""
            entries.append(
                {
                    "code": m.group(1),
                    "name": m.group(2).strip(),
                    "level": "Secção",
                    "section": m.group(1),
                    "path": "",
                }
            )
        elif (m := RE_DIVISAO.match(linha)) is not None:
            atual_divisao = m.group(1)
            atual_grupo = ""
            entries.append(
                {
                    "code": m.group(1),
                    "name": m.group(2).strip(),
                    "level": "Divisão",
                    "section": atual_seccao,
                    "path": f"Secção {atual_seccao}",
                }
            )
        elif (m := RE_GRUPO.match(linha)) is not None:
            atual_grupo = m.group(1)
            entries.append(
                {
                    "code": m.group(1),
                    "name": m.group(2).strip(),
                    "level": "Grupo",
                    "section": atual_seccao,
                    "path": f"Divisão {atual_divisao}",
                }
            )
        elif (m := RE_CLASSE_SUB.match(linha)) is not None:
            entries.append(
                {
                    "code": m.group(1),
                    "name": m.group(3).strip(),
                    "level": "Classe",
                    "section": atual_seccao,
                    "path": f"Divisão {atual_divisao} › Grupo {atual_grupo}",
                }
            )
            entries.append(
                {
                    "code": m.group(2),
                    "name": m.group(3).strip(),
                    "level": "Subclasse",
                    "section": atual_seccao,
                    "path": f"Divisão {atual_divisao} › Grupo {atual_grupo} › Classe {m.group(1)}",
                }
            )
        elif (m := RE_CLASSE.match(linha)) is not None:
            entries.append(
                {
                    "code": m.group(1),
                    "name": m.group(2).strip(),
                    "level": "Classe",
                    "section": atual_seccao,
                    "path": f"Divisão {atual_divisao} › Grupo {atual_grupo}",
                }
            )
        elif (m := RE_SUBCLASSE.match(linha)) is not None:
            entries.append(
                {
                    "code": m.group(1),
                    "name": m.group(2).strip(),
                    "level": "Subclasse",
                    "section": atual_seccao,
                    "path": f"Divisão {atual_divisao} › Grupo {atual_grupo} › Classe {m.group(1)[:4]}",
                }
            )

    catalog = CaeCatalog(entries)
    if path is None:
        _catalog_cache = catalog
    return catalog


def get_cae_catalog() -> CaeCatalog:
    """Devolve o catálogo global já carregado, ou carrega-o."""
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = load_cae_catalog()
    return _catalog_cache


def label_for_cae(code: str) -> str:
    """Devolve a descrição de um código CAE, ou o próprio código."""
    entry = get_cae_catalog().find(code)
    return entry["name"] if entry else code


def all_cae_entries(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Devolve todas as entradas do catálogo, opcionalmente limitadas."""
    entries = get_cae_catalog().entries
    return entries[:limit] if limit is not None else entries


def search_cae_entries(q: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Pesquisa entradas CAE por código ou designação."""
    return get_cae_catalog().search(q, limit=limit)
