"""Que tamanho é que o push tem de enviar e o que o engorda.

O push falhou com `RPC failed; HTTP 500` — sintoma típico de um pacote demasiado
grande (ou de um ficheiro acima do limite do GitHub). Este script mede:

* o total de bytes dos objetos entre `origin/main` e `HEAD`;
* os 20 maiores *blobs* desse intervalo, com o caminho.
"""
from __future__ import annotations

import subprocess
import sys

CWD = r"C:\LLMFinance"
RANGE = ["origin/main..HEAD"]


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=CWD, capture_output=True, check=False).stdout


def main() -> int:
    revs = git("rev-list", "--objects", *RANGE).decode("utf-8", "replace")
    lines = [line for line in revs.splitlines() if line.strip()]
    print(f"objetos no intervalo: {len(lines)}")

    # caminho de cada sha (o `rev-list --objects` já dá "sha caminho")
    paths: dict[str, str] = {}
    shas: list[str] = []
    for line in lines:
        sha, _, path = line.partition(" ")
        shas.append(sha)
        if path:
            paths[sha] = path

    batch = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        cwd=CWD,
        input="\n".join(shas).encode(),
        capture_output=True,
        check=False,
    ).stdout.decode("utf-8", "replace")

    total = 0
    blobs: list[tuple[int, str]] = []
    for row in batch.splitlines():
        parts = row.split()
        if len(parts) != 3:
            continue
        sha, kind, size = parts
        size = int(size)
        total += size
        if kind == "blob":
            blobs.append((size, paths.get(sha, sha)))

    print(f"total a enviar: {total / 1024 / 1024:.1f} MiB")
    blobs.sort(reverse=True)
    print("\nmaiores blobs:")
    for size, path in blobs[:20]:
        flag = "  <-- ACIMA DE 100 MiB!" if size > 100 * 1024 * 1024 else ""
        print(f"  {size / 1024 / 1024:8.1f} MiB  {path}{flag}")

    over = [p for s, p in blobs if s > 100 * 1024 * 1024]
    if over:
        print(f"\n{len(over)} ficheiro(s) acima do limite de 100 MiB do GitHub:")
        for path in over:
            print("  -", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
