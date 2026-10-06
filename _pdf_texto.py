"""Le o texto dos PDF gerados (streams FlateDecode) para conferir a assinatura.

Não substitui o ver com os olhos, mas confirma que o cabeçalho e o rodapé
existem **em todas** as páginas e que `{nb}` foi substituído pelo total.
"""

import pathlib
import re
import sys
import zlib

if len(sys.argv) < 2:
    raise SystemExit("uso: python _pdf_texto.py <ficheiro.pdf> [...]")


def blocos(data: bytes):
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        raw = data[start:end]
        try:
            yield zlib.decompress(raw)
        except Exception:
            yield raw


def linhas(pdf: pathlib.Path):
    data = pdf.read_bytes()
    encontrados = []
    for bloco in blocos(data):
        for texto in re.finditer(rb"\((?:[^()\\]|\\.)*\)", bloco):
            encontrados.append(texto.group(0)[1:-1].decode("latin-1"))
    return encontrados


for argumento in sys.argv[1:]:
    pdf = pathlib.Path(argumento)
    data = pdf.read_bytes()
    textos = linhas(pdf)
    paginas = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    interessantes = [t for t in textos if re.search(r"IQ OS|Plataforma|emitido|p.gina|nb", t)]
    print(f"\n=== {pdf.name} · {len(data)}B · {paginas} páginas · assinatura {data[:5]!r}")
    for linha in interessantes:
        print(f"   {linha}")
    if b"{nb}" in data:
        print("   AVISO: {nb} não foi substituído")
