"""Depura blocos anómalos: Porto (sem presidente), Alandroal (0 nomes), Cascais (6 de 11)."""
import openpyxl

CAMINHO = ".tmp_cne/2025al-mapa-oficial_retificado/mapa_3_eleitos_retificado.xlsx"
folha = openpyxl.load_workbook(CAMINHO, read_only=True, data_only=True)["Folha1"]
linhas = [list(linha) for linha in folha.iter_rows(values_only=True)]


def mostrar(alvo: str, limite: int = 30):
    for indice, linha in enumerate(linhas):
        primeira = "" if linha[0] is None else str(linha[0]).strip()
        segunda = "" if linha[1] is None else str(linha[1]).strip()
        terceira = "" if linha[2] is None else str(linha[2]).strip()
        quarta = "" if linha[3] is None else str(linha[3]).strip()
        if primeira.isdigit() and segunda.lower() == alvo.lower() and quarta == "CM":
            print("=" * 70)
            print(f"linha {indice + 1}: {primeira} | {segunda} | {terceira} | {quarta}")
            for deslocamento in range(1, limite):
                seguinte = linhas[indice + deslocamento]
                valores = [("" if v is None else str(v)) for v in seguinte]
                if deslocamento > 1 and valores[0].isdigit():
                    break
                print(f"  +{deslocamento}: {valores}")
            return
    print(alvo, "-> não encontrado")


for concelho in ("PORTO", "ALANDROAL", "CASCAIS", "OEIRAS", "BRAGA"):
    mostrar(concelho)

print()
print("=== concelhos com sufixo de região autónoma ===")
for linha in linhas:
    segunda = "" if linha[1] is None else str(linha[1]).strip()
    if "(R.A." in segunda:
        print("  ", [("" if v is None else str(v)) for v in linha])
