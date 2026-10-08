"""Mostra as linhas de um intervalo com ascii() (para ver aspas e escapes)."""
import io
import sys

CAMINHO = r"C:\LLMFinance\finance-llm\api\deep_search_service.py"
inicio = int(sys.argv[1])
fim = int(sys.argv[2])

linhas = io.open(CAMINHO, encoding="utf-8").read().splitlines()
for numero in range(inicio - 1, min(fim, len(linhas))):
    print(numero + 1, ascii(linhas[numero])[:160])
