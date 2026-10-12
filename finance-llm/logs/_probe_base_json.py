"""Como é o JSON dentro do ZIP do Portal Base? (chaves e forma do ficheiro)

O ZIP do ano traz **um** ficheiro `Contratos<ano>.json` (centenas de MB). Antes de
escrever o importador, isto diz o que interessa: é um *array* JSON, um ficheiro
NDJSON ou um objeto? Quais são as chaves de cada contrato? Que tipos têm?

Uso::

    python -u /app/logs/_probe_base_json.py --zip /tmp/base/contratos2026.zip
    python -u /app/logs/_probe_base_json.py --zip /tmp/base/contratos2026.zip --contar
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional


def membro_json(zipper: zipfile.ZipFile) -> Optional[zipfile.ZipInfo]:
    return next((m for m in zipper.infolist() if m.filename.lower().endswith(".json")), None)


def amostra(zip_path: Path, *, mostrar: int = 16 * 1024) -> None:
    with zipfile.ZipFile(zip_path) as zipper:
        membro = membro_json(zipper)
        if not membro:
            print("sem membro JSON no zip:", [m.filename for m in zipper.infolist()])
            return
        print(
            f"membro: {membro.filename} · {membro.file_size / 1e6:.1f} MB · "
            f"comprimido {membro.compress_size / 1e6:.1f} MB"
        )
        with zipper.open(membro) as fluxo:
            inicio = fluxo.read(mostrar)
        texto = inicio.decode("utf-8", errors="replace")
        print("\nprimeiros 300 caracteres:")
        print(" ", texto[:300].replace("\n", "\\n"))
        print("\nforma detetada:", _forma(texto))
        registo = _primeiro_registo(texto)
        if registo:
            print(f"\nchaves do 1.º registo ({len(registo)}):")
            for chave, valor in registo.items():
                print(f"  {chave:34} {type(valor).__name__:6} {str(valor)[:72]}")


def _forma(texto: str) -> str:
    limpo = texto.lstrip()
    if limpo.startswith("["):
        return "array JSON"
    if limpo.startswith("{"):
        return "objeto JSON (1 registo por linha? NDJSON?)"
    return "desconhecida"


def _primeiro_registo(texto: str) -> Optional[Dict[str, Any]]:
    inicio = texto.find("{")
    if inicio < 0:
        return None
    codificador = json.JSONDecoder()
    try:
        valor, _ = codificador.raw_decode(texto[inicio:])
    except ValueError:
        fim = texto.rfind("}")
        if fim <= inicio:
            return None
        try:
            valor, _ = codificador.raw_decode(texto[inicio : fim + 1])
        except ValueError:
            return None
    return valor if isinstance(valor, dict) else None


def contar(zip_path: Path, *, limite: int = 0) -> None:
    """Conta registos com um parser incremental (não carrega o ficheiro todo)."""
    with zipfile.ZipFile(zip_path) as zipper:
        membro = membro_json(zipper)
        if not membro:
            return
        with zipper.open(membro) as fluxo:
            codificador = json.JSONDecoder()
            buffer = ""
            total = 0
            while True:
                pedaco = fluxo.read(1 << 20).decode("utf-8", errors="replace")
                buffer += pedaco
                indice = 0
                while True:
                    inicio = buffer.find("{", indice)
                    if inicio < 0:
                        buffer = buffer[indice:]
                        break
                    try:
                        _, fim = codificador.raw_decode(buffer, inicio)
                    except ValueError:
                        buffer = buffer[inicio:]
                        break
                    total += 1
                    indice = fim
                    if limite and total >= limite:
                        print(f"registos lidos (limite): {total}")
                        return
                if not pedaco:
                    break
            print(f"registos no ficheiro: {total}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspecionar o JSON do Portal Base.")
    parser.add_argument("--zip", required=True)
    parser.add_argument("--contar", action="store_true")
    args = parser.parse_args()

    zip_path = Path(args.zip)
    print(f"zip: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")
    amostra(zip_path)
    if args.contar:
        contar(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
