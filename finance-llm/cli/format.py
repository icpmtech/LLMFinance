"""Cores, tabelas e formatação de valores para o terminal.

Sem dependências externas: as cores são sequências ANSI e são desativadas
automaticamente quando a saída não é um terminal (ou quando `NO_COLOR` está
definido), o que mantém o CLI utilizável em pipelines.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Iterable, Sequence

_ENABLED = sys.stdout.isatty() and not os.getenv("NO_COLOR")
_UNICODE = True


def configure(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = enabled


def configure_unicode(enabled: bool) -> None:
    """Ativa/desativa símbolos Unicode (caixas, vistos, euros)."""
    global _UNICODE
    _UNICODE = enabled


def symbol(unicode_text: str, ascii_text: str) -> str:
    """Escolhe o símbolo conforme o que a consola consegue representar."""
    return unicode_text if _UNICODE else ascii_text


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ENABLED else text


def bold(text: Any) -> str:
    return _paint("1", str(text))


def dim(text: Any) -> str:
    return _paint("2", str(text))


def green(text: Any) -> str:
    return _paint("32", str(text))


def red(text: Any) -> str:
    return _paint("31", str(text))


def yellow(text: Any) -> str:
    return _paint("33", str(text))


def cyan(text: Any) -> str:
    return _paint("36", str(text))


def title(text: str) -> str:
    return bold(cyan(text))


def ok(text: Any) -> str:
    return green(f"{symbol('✔', 'OK')} {text}")


def fail(text: Any) -> str:
    return red(f"{symbol('✖', 'X')} {text}")


def warn(text: Any) -> str:
    return yellow(f"! {text}")


def money(value: Any, *, currency: str | None = None) -> str:
    """Formata um valor monetário à portuguesa (ex.: `1 234 567,89 €`)."""
    unit = currency if currency is not None else symbol("€", "EUR")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—" if _UNICODE else "-"
    if abs(number) >= 1_000_000_000:
        return f"{number / 1_000_000_000:,.2f} mM{unit}".replace(",", " ").replace(".", ",")
    text = f"{number:,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} {unit}"


def number(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—" if _UNICODE else "-"


def percent(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f} %".replace(".", ",")
    except (TypeError, ValueError):
        return "—" if _UNICODE else "-"


def short_date(value: Any, with_time: bool = False) -> str:
    """Converte ISO/epoch numa data legível (`16/09/2026` ou com hora)."""
    if value in (None, ""):
        return "—" if _UNICODE else "-"
    text = str(value)
    parsed: datetime | None = None
    try:
        if text.isdigit():
            parsed = datetime.fromtimestamp(int(text[:10]))
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, OSError):
        return text[:10]
    return parsed.strftime("%d/%m/%Y %H:%M") if with_time else parsed.strftime("%d/%m/%Y")


def truncate(text: Any, width: int) -> str:
    value = "" if text is None else str(text)
    value = value.replace("\n", " ").strip()
    if len(value) <= width:
        return value
    return value[: max(1, width - 1)] + symbol("…", ".")


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], *, widths: Sequence[int] | None = None) -> str:
    """Tabela simples com cabeçalho realçado (pensada para 80–160 colunas)."""
    materialized = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    if widths is None:
        widths = [
            min(48, max(len(str(headers[index])), *(len(row[index]) for row in materialized))) if materialized else len(str(headers[index]))
            for index in range(len(headers))
        ]
    lines = ["  ".join(bold(truncate(head, widths[index]).ljust(widths[index])) for index, head in enumerate(headers))]
    lines.append("  ".join(dim(symbol("─", "-") * width) for width in widths))
    for row in materialized:
        lines.append("  ".join(truncate(cell, widths[index]).ljust(widths[index]) for index, cell in enumerate(row)))
    return "\n".join(lines)


def field(label: str, value: Any, *, width: int = 16) -> str:
    """Linha `rótulo   valor` alinhada (usada nos resumos)."""
    return f"{dim(label.ljust(width))} {value}"
