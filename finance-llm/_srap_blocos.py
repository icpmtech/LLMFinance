"""Diagnóstico (temporário) dos blocos como o serviço os vê."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from api import remuneracoes_ap_service as servico  # noqa: E402

import pymupdf  # noqa: E402

doc = pymupdf.open(servico.PASTA / "pdf" / servico.FICHEIROS[2025])
saida = io.open(Path(os.environ["TEMP"]) / "srap_blocos.txt", "w", encoding="utf-8")
for pno in [int(a) for a in sys.argv[1:]]:
    page = doc[pno - 1]
    texto = page.get_text()
    saida.write(f"\n================ página {pno} ================\n")
    saida.write("capa? " + str(servico._e_capa(texto)) + " | notas? " + str(servico._notas_da_seccao(texto)) + "\n")
    linhas = [linha for linha in servico._paginas_em_linhas(page) if 55 < linha["y"] < 800]
    for bloco in servico._blocos(linhas, (140.0, 400.0)):
        linha_nome = bloco["linhas"].get("p") or bloco["linhas"].get("i")
        saida.write(f"\nbloco y={bloco['y']:.1f} primeiro={bloco['primeiro']} marcadores={sorted(bloco['linhas'])}\n")
        for chave, linha in sorted(bloco["linhas"].items()):
            celulas = servico._celulas(linha, a_partir_de=140.0)
            saida.write(
                f"   {chave}) nome={servico._nome_da_coluna(linha)!r} "
                f"celulas={[c['texto'] for c in celulas]}\n"
            )
        saida.write(f"   titulos={[servico._nome_da_coluna(linha) for linha in bloco['titulos']]}\n")
saida.close()
print("escrito", Path(os.environ["TEMP"]) / "srap_blocos.txt")
