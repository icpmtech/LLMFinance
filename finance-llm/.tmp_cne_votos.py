"""Compara votos e mandatos (mapa_1/mapa_2) com os nomes (mapa_3) em Braga e Setúbal."""
import openpyxl

PASTA = ".tmp_cne/2025al-mapa-oficial_retificado"
livro1 = openpyxl.load_workbook(f"{PASTA}/mapa_1_resultados_retificado.xlsx", read_only=True, data_only=True)["Folha1"]
livro2 = openpyxl.load_workbook(f"{PASTA}/mapa_2_perc_mandatos_retificado.xlsx", read_only=True, data_only=True)["Folha1"]

linhas1 = [list(linha) for linha in livro1.iter_rows(values_only=True)]
linhas2 = [list(linha) for linha in livro2.iter_rows(values_only=True)]

cabecalho_partidos = linhas1[3]
print("mapa_1: colunas com sigla:")
for indice, valor in enumerate(cabecalho_partidos):
    if valor:
        print(f"   {indice}: {valor!r}")

for concelho in ("Braga", "Setúbal", "Cascais"):
    print()
    print("=" * 60, concelho)
    for linhas, etiqueta in ((linhas1, "mapa_1"), (linhas2, "mapa_2")):
        for linha in linhas:
            if (
                len(linha) > 3
                and str(linha[0]).strip().isdigit()
                and str(linha[1]).strip().lower() == concelho.lower()
                and str(linha[3]).strip() == "CM"
            ):
                print(f"  {etiqueta}:")
                for indice, valor in enumerate(linha):
                    if valor not in (None, ""):
                        cabecalho = cabecalho_partidos[indice] if indice < len(cabecalho_partidos) and cabecalho_partidos[indice] else f"[{indice}]"
                        print(f"     {indice:3} {str(cabecalho)[:22]:24} {valor}")
                break
