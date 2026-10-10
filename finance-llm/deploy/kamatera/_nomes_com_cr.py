#!/usr/bin/env python3
"""Lista nomes com retorno de carro ou mudanca de linha na arvore do IQ OS.

Porque e que isto existe
------------------------
Um deploy antigo criou ficheiros e pastas com um `\\r` no **nome** (nao no
conteudo): `compose.yml\\r` ao lado de `compose.yml`, `edge\\r` ao lado de `edge`.
Sao invisiveis num `ls` normal e aparecem como "duplicados impossiveis" num
`find` que imprime caminhos relativos.

Nao e so confusao. Sao ficheiros que nenhuma ferramenta usa, mas que qualquer
script que percorra a pasta vai encontrar -- e um `for f in $(ls)` ou um `*.yml`
apanha os dois. O custo de os deixar la aparece mais tarde, longe da causa.

Corre na VM, com o script pelo stdin (`python3 -`), para nao ter de atravessar
aspas pelo PowerShell e pelo ssh.
"""
from __future__ import annotations

import os
import sys

RAIZES = sys.argv[1:] or ["/opt/iqos"]

maus: list[tuple[str, str]] = []
for raiz in RAIZES:
    for pasta, dirs, ficheiros in os.walk(raiz):
        for nome in dirs + ficheiros:
            if "\r" in nome or "\n" in nome:
                caminho = os.path.join(pasta, nome)
                try:
                    detalhe = str(os.path.getsize(caminho)) if os.path.isfile(caminho) else "dir"
                except OSError as exc:
                    detalhe = f"erro {exc}"
                maus.append((caminho, detalhe))

print(f"nomes com CR/LF: {len(maus)}")
for caminho, detalhe in sorted(maus):
    # `repr` mostra o \\r em vez de o executar. Sem isto o terminal comia-o e a
    # listagem parecia so nomes repetidos -- que foi exatamente o que enganou a
    # primeira verificacao.
    print(f"{detalhe:>10}  {caminho!r}")
