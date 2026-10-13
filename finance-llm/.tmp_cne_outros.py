"""Inspecciona mapa_1_resultados e mapa_2_perc_mandatos (temporário)."""
import openpyxl

for nome in ("mapa_1_resultados_retificado", "mapa_2_perc_mandatos_retificado", "mapa_anexo"):
    caminho = f".tmp_cne/2025al-mapa-oficial_retificado/{nome}.xlsx"
    livro = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    folha = livro[livro.sheetnames[0]]
    linhas = [list(linha) for linha in folha.iter_rows(values_only=True)]
    larguras = sorted({len(linha) for linha in linhas})
    print("=" * 72)
    print(nome, "| folhas:", livro.sheetnames, "| linhas:", len(linhas), "| larguras:", larguras[:6])
    for numero, linha in enumerate(linhas[:14], start=1):
        preenchidas = [("" if v is None else str(v))[:26] for v in linha]
        print(f"  {numero}: {preenchidas}")
