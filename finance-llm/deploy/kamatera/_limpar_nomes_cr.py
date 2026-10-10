#!/usr/bin/env python3
"""Limpa nomes com retorno de carro na arvore do IQ OS.

Contexto
--------
Um deploy antigo criou ficheiros e pastas com um `\\r` no **nome**:
`compose.yml\\r` ao lado de `compose.yml`, e uma pasta `edge\\r` ao lado de
`edge`. Nao se veem num `ls` e nao servem para nada -- nenhum script, nenhum
`docker compose` e nenhum bind mount lhes toca. Mas aparecem a quem percorra a
pasta, e foi o que fez uma verificacao de integridade falhar com um "duplicado
impossivel" (dois `compose.yml` no mesmo caminho relativo).

Seguranca
---------
Corre em **simulacao por omissao**: lista o que apagaria e sai. So apaga com
`--aplicar`. E o que se quer num utilitario destrutivo que corre como root numa
maquina sem firewall -- a lista tem de ser lida antes, nao depois.

Antes de apagar uma pasta, mostra o que tem dentro. Se tiver algo que nao
reconheca, a decisao fica de quem lê, e nao no `rm`.

Uso (o script vai pelo stdin do ssh, para nao haver aspas a atravessar):
    python3 -                  -> simulacao
    python3 - --aplicar        -> apaga
    python3 - --aplicar /outra/raiz
"""
from __future__ import annotations

import os
import shutil
import sys

argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
APLICAR = "--aplicar" in sys.argv
RAIZES = argumentos or ["/opt/iqos"]


def tem_cr(nome: str) -> bool:
    return "\r" in nome or "\n" in nome


def recolher() -> list[str]:
    alvos: list[str] = []
    for raiz in RAIZES:
        for pasta, dirs, ficheiros in os.walk(raiz):
            for nome in dirs + ficheiros:
                if tem_cr(nome):
                    alvos.append(os.path.join(pasta, nome))
    return sorted(alvos)


alvos = recolher()
print(f"{'A APAGAR' if APLICAR else 'SIMULACAO'} -- {len(alvos)} entradas com CR/LF")

for caminho in alvos:
    if os.path.isdir(caminho) and not os.path.islink(caminho):
        conteudo = sorted(os.listdir(caminho))
        print(f"\n  dir   {caminho!r}  ({len(conteudo)} entradas)")
        for nome in conteudo:
            sub = os.path.join(caminho, nome)
            try:
                tamanho = os.path.getsize(sub) if os.path.isfile(sub) else "dir"
            except OSError as exc:
                tamanho = f"erro {exc}"
            print(f"          {tamanho:>10}  {nome!r}")
    else:
        print(f"\n  ficheiro {caminho!r}  ({os.path.getsize(caminho)} bytes)")

if not APLICAR:
    print("\nNada foi apagado. Repetir com --aplicar.")
    raise SystemExit(0)

print()
apagados = 0
for caminho in alvos:
    try:
        if os.path.isdir(caminho) and not os.path.islink(caminho):
            shutil.rmtree(caminho)
        else:
            os.remove(caminho)
        print(f"  apagado  {caminho!r}")
        apagados += 1
    except OSError as exc:
        print(f"  FALHOU   {caminho!r}: {exc}")

print(f"\n{apagados} de {len(alvos)} apagados.")
restantes = recolher()
print(f"a verificar: {len(restantes)} nomes com CR/LF ainda presentes")
for caminho in restantes:
    print(f"  ainda la: {caminho!r}")
