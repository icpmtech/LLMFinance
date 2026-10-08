"""Traz para o host os ficheiros que só existem dentro do container do backend.

`/app/exports` e `/app/debug_mj` **não** estão em nenhum volume do compose, por
isso o que a recolha grava lá dentro desaparece quando o container é recriado
(aconteceu a 2026-10-07/08 com o JSON do NIF 514024674). Este script compara uma
pasta *staging* (saída de `docker cp`) com a pasta equivalente do host e copia o
que falta ou está mais recente, **sem apagar nada**: em caso de conflito o
ficheiro do host é guardado em `_backup_<carimbo>/`.

Uso (primeiro sem `--aplicar`, só para ver o relatório)::

    python logs/_sincronizar_container_para_host.py \
        logs/_from_container_20261008-163902 --aplicar

Por omissão faz `--dry-run` (relatório). O `--aplicar` copia e faz a cópia de
segurança dos ficheiros que substitui.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path


def _sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as ficheiro:
        for bloco in iter(lambda: ficheiro.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _resumo(relatorio: dict[str, list[str]]) -> str:
    linhas = []
    for chave in ("iguais", "novos", "atualiza", "antigos"):
        itens = relatorio[chave]
        linhas.append(f"  {chave:11} {len(itens):5}")
    return "\n".join(linhas)


def sincronizar(origem: Path, destino: Path, aplicar: bool, backup_dir: Path) -> dict[str, list[str]]:
    """Compara ``origem`` com ``destino`` e (se ``aplicar``) copia o que falta.

    Devolve o relatório por categoria para o chamador poder imprimir/verificar.
    """
    relatorio: dict[str, list[str]] = {chave: [] for chave in ("iguais", "novos", "atualiza", "antigos")}
    if not origem.exists():
        raise SystemExit(f"Origem inexistente: {origem}")

    for origem_ficheiro in sorted(origem.rglob("*")):
        if not origem_ficheiro.is_file():
            continue
        relativo = origem_ficheiro.relative_to(origem)
        destino_ficheiro = destino / relativo

        if not destino_ficheiro.exists():
            relatorio["novos"].append(str(relativo))
            if aplicar:
                destino_ficheiro.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origem_ficheiro, destino_ficheiro)
            continue

        if _sha256(origem_ficheiro) == _sha256(destino_ficheiro):
            relatorio["iguais"].append(str(relativo))
            continue

        # Conteúdo diferente: manda o mais recente; o outro é preservado no backup.
        if origem_ficheiro.stat().st_mtime > destino_ficheiro.stat().st_mtime:
            relatorio["atualiza"].append(str(relativo))
            if aplicar:
                destino_ficheiro.parent.mkdir(parents=True, exist_ok=True)
                copia_seguranca = backup_dir / relativo
                copia_seguranca.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destino_ficheiro, copia_seguranca)
                shutil.copy2(origem_ficheiro, destino_ficheiro)
        else:
            relatorio["antigos"].append(str(relativo))

    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copia exports/debug_mj do container para o host sem perder nada.")
    parser.add_argument("staging", type=Path, help="Pasta criada com `docker cp` (contém exports/ e/ou debug_mj/)")
    parser.add_argument("--host", type=Path, default=Path(__file__).resolve().parents[1], help="Raiz do projeto no host")
    parser.add_argument("--aplicar", action="store_true", help="Copiar de facto (por omissão só relata)")
    args = parser.parse_args(argv)

    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = args.host / "logs" / f"_backup_{carimbo}"
    dry = not args.aplicar

    if dry:
        print("### MODO RELATÓRIO (nada será alterado) — use --aplicar para copiar\n")

    total_novos = 0
    for nome in ("exports", "debug_mj"):
        origem = args.staging / nome
        if not origem.exists():
            continue
        destino = args.host / nome
        print(f"== {nome}: {origem}  ->  {destino}")
        relatorio = sincronizar(origem, destino, aplicar=args.aplicar, backup_dir=backup_dir)
        print(_resumo(relatorio))
        total_novos += len(relatorio["novos"]) + len(relatorio["atualiza"])
        for chave in ("novos", "atualiza"):
            for item in relatorio[chave][:10]:
                print(f"     {chave[:5]}: {item}")
            if len(relatorio[chave]) > 10:
                print(f"     … e mais {len(relatorio[chave]) - 10}")

    if dry:
        print(f"\nA aplicar: {total_novos} ficheiro(s). Nada foi alterado.")
    else:
        print(f"\nAplicado: {total_novos} ficheiro(s). Cópias de segurança em {backup_dir} (se houve substituições).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
