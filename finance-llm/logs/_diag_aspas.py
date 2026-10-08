"""Diagnóstico: onde está a aspa tripla que desalinha o tokenizador."""
import io
import tokenize

CAMINHO = r"C:\LLMFinance\finance-llm\api\deep_search_service.py"

texto = io.open(CAMINHO, encoding="utf-8").read()
print(f"linhas: {len(texto.splitlines())}")
print(f"'\"\"\"': {texto.count(chr(34) * 3)}")
print(f"chr(39)*3: {texto.count(chr(39) * 3)}")

print("\n--- tokens de string entre as linhas 300 e 600 ---")
with open(CAMINHO, "rb") as ficheiro:
    try:
        for token in tokenize.tokenize(ficheiro.readline):
            if token.type == tokenize.STRING and 300 <= token.start[0] <= 600:
                inicio = token.string[:60].replace("\n", "\\n")
                print(f"  {token.start[0]:>4}-{token.end[0]:<4} {ascii(inicio)}")
            if token.type == tokenize.ERRORTOKEN and 300 <= token.start[0] <= 600:
                print(f"  {token.start[0]:>4} ERRORTOKEN {ascii(token.string)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  tokenize falhou: {type(exc).__name__}: {exc}")
