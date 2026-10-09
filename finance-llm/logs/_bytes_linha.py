"""Mostra bytes nao-ASCII e o ascii() de linhas indicadas (diagnostico pontual)."""
import io
import sys

CAMINHO = r"C:\LLMFinance\finance-llm\tests\test_deep_search_analysis.py"
linhas = io.open(CAMINHO, encoding="utf-8").read().splitlines()

for numero in range(355, 371):
    linha = linhas[numero - 1]
    suspeitos = [
        (posicao, hex(ord(ch)))
        for posicao, ch in enumerate(linha)
        if ord(ch) > 127 or ord(ch) in (0x200B, 0x200C, 0x200D, 0xFEFF, 0xA0)
    ]
    print(numero, ascii(linha)[:120])
    if suspeitos:
        print("      suspeitos:", suspeitos)
