"""Lê o texto pintado num PDF de relatório (sem pypdf) para validar o conteúdo.

Descomprime os `stream` com zlib e extrai os operandos dos `Tj`. Serve só para
verificar, em testes, que o PDF tem as secções esperadas.
"""
from __future__ import annotations

import re
import sys
import zlib

PADRAO_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
PADRAO_TJ = re.compile(rb"\((?:\\.|[^()\\])*\)\s*Tj", re.S)


def descomprimir(bruto: bytes) -> bytes:
    """Os streams do reportlab vêm em ASCII85 + Flate (por vezes sem ASCII85)."""
    dados = bruto.strip()
    if dados.endswith(b"~>"):
        try:
            import base64

            dados = base64.a85decode(dados, adobe=True)
        except Exception:
            pass
    try:
        return zlib.decompress(dados)
    except Exception:
        return dados


def extrair(caminho: str) -> list[str]:
    data = open(caminho, "rb").read()
    linhas: list[str] = []
    for bloco in PADRAO_STREAM.finditer(data):
        plano = descomprimir(bloco.group(1))
        for achado in PADRAO_TJ.finditer(plano):
            literal = achado.group(0)[: achado.group(0).rfind(b")")]
            texto = literal[1:].decode("latin-1", "replace")
            texto = re.sub(r"\\([()\\])", r"\1", texto)
            linhas.append(texto)
    return linhas


if __name__ == "__main__":
    caminho = sys.argv[1]
    linhas = extrair(caminho)
    print(f"bytes={len(open(caminho, 'rb').read())} linhas={len(linhas)}")
    for linha in linhas:
        print(" ", linha[:120])

    if not linhas:
        # Diagnóstico: mostra o início dos streams descomprimidos para ver os operadores.
        data = open(caminho, "rb").read()
        for i, bloco in enumerate(PADRAO_STREAM.finditer(data)):
            bruto = bloco.group(1)
            try:
                plano = zlib.decompress(bruto)
            except Exception:
                plano = bruto
            print(f"--- stream {i} ({len(plano)} bytes) ---")
            print(plano[:500].decode("latin-1", "replace"))
