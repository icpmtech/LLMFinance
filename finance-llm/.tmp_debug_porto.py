"""Depura a leitura de votos: Porto e Viseu."""
import openpyxl

from api import mapa_oficial_cne as cne

PASTA = "data/remuneracoes"
livro = openpyxl.load_workbook(f"{PASTA}/mapa_1_resultados_retificado.xlsx", read_only=True, data_only=True)["Folha1"]
linhas = [list(linha) for linha in livro.iter_rows(values_only=True)]
cabecalho = [str(v).strip() if v else "" for v in linhas[3]]

for alvo in ("Porto", "Viseu", "Alandroal"):
    for linha in linhas:
        if (
            len(linha) > 3
            and linha[0] is not None
            and str(linha[1]).strip().lower() == alvo.lower()
            and str(linha[3]).strip() == "CM"
        ):
            print("=" * 70, alvo)
            for indice, valor in enumerate(linha):
                if valor not in (None, ""):
                    nome = cabecalho[indice] if indice < len(cabecalho) and cabecalho[indice] else f"[{indice}]"
                    print(f"   {indice:3} {nome:20} {valor}")
            break

resultados = cne.ler_resultados(f"{PASTA}/mapa_1_resultados_retificado.xlsx")
for chave in ("131200|CM", "182300|CM"):
    print(chave, "->", (resultados.get(chave) or {}).get("votos", [])[:5])
