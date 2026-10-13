"""Lista as pastas de data/ na VM com contagem e tamanho, para comparar com o PC."""

import os

BASE = "/opt/iqos/servicos/backend/data"

print("=== pastas em data/ (VM) ===")
linhas = []
for nome in sorted(os.listdir(BASE)):
    caminho = os.path.join(BASE, nome)
    if not os.path.isdir(caminho):
        continue
    ficheiros = 0
    total = 0
    for raiz, _, nomes in os.walk(caminho):
        for f in nomes:
            try:
                total += os.path.getsize(os.path.join(raiz, f))
                ficheiros += 1
            except OSError:
                pass
    linhas.append((nome, ficheiros, total))

for nome, ficheiros, total in linhas:
    print(f"  {nome:<44} {ficheiros:>5} fich  {total / 1048576:>9.1f} MB")
print(f"\n  total: {len(linhas)} pastas")
