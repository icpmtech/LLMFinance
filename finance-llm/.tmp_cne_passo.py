"""Depura o parser do mapa_3 num bloco concreto, passo a passo."""
import sys

import openpyxl

from api.mapa_oficial_cne import _sigla_like, _vazio

CAMINHO = ".tmp_cne/2025al-mapa-oficial_retificado/mapa_3_eleitos_retificado.xlsx"
ALVO = sys.argv[1] if len(sys.argv) > 1 else "Braga"

folha = openpyxl.load_workbook(CAMINHO, read_only=True, data_only=True)["Folha1"]
linhas = [list(linha) for linha in folha.iter_rows(values_only=True)]

inicio = None
for indice, linha in enumerate(linhas):
    primeira = "" if linha[0] is None else str(linha[0]).strip()
    segunda = "" if linha[1] is None else str(linha[1]).strip()
    quarta = "" if linha[3] is None else str(linha[3]).strip()
    if primeira.isdigit() and segunda.lower() == ALVO.lower() and quarta == "CM":
        inicio = indice
        break

print("bloco começa na linha", inicio + 1)
for deslocamento in range(1, 12):
    linha = linhas[inicio + deslocamento]
    primeira = "" if linha[0] is None else str(linha[0]).strip()
    if deslocamento > 1 and primeira.isdigit():
        print("  (fim do bloco)")
        break
    preenchidas = [str(v) for v in linha if not _vazio(v)]
    marcas = [(str(v), _sigla_like(str(v))) for v in preenchidas]
    print(f"  +{deslocamento}: {marcas}")
    print(f"        eh_sigla={bool(preenchidas) and all(m[1] for m in marcas)}")
