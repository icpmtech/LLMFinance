"""O que vem dentro do ZIP do Portal Base? (formato real, sem adivinhar)

Descarrega o ZIP de um ano do conjunto «Contratos Públicos - Portal Base» do
dados.gov.pt, lista o que vem lá dentro e mostra o cabeçalho e as primeiras
linhas do ficheiro de dados, com a codificação e o separador detetados. É o passo
que evita escrever um importador para um formato imaginado.

Uso::

    python -u /app/logs/_probe_base_zip.py               # ano atual
    python -u /app/logs/_probe_base_zip.py --ano 2019
    python -u /app/logs/_probe_base_zip.py --listar      # só os recursos, sem descarregar
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

API = "https://dados.gov.pt/api/1/datasets/contratos-publicos-portal-base-impic-contratos-de-2012-a-2026/"
DESTINO = Path("/tmp/base")


def recursos() -> List[Dict[str, Any]]:
    with httpx.Client(timeout=120, follow_redirects=True) as cliente:
        dados = cliente.get(API).json()
    itens: List[Dict[str, Any]] = []
    for recurso in dados.get("resources") or []:
        titulo = str(recurso.get("title") or "")
        ano = "".join(ch for ch in titulo if ch.isdigit())[:4]
        itens.append(
            {
                "titulo": titulo,
                "ano": ano,
                "formato": recurso.get("format"),
                "bytes": recurso.get("filesize"),
                "atualizado": (recurso.get("last_modified") or "")[:19],
                "url": recurso.get("url"),
                "sha1": ((recurso.get("checksum") or {}).get("value")),
            }
        )
    itens.sort(key=lambda item: (item["ano"], item["formato"] or ""))
    return itens


def detetar_leitura(amostra: bytes) -> Dict[str, Any]:
    """Descobre codificação e separador a partir dos primeiros bytes."""
    deteccoes: List[Dict[str, Any]] = []
    for codificacao in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            texto = amostra.decode(codificacao)
        except UnicodeDecodeError:
            continue
        linha = texto.splitlines()[0] if texto.splitlines() else ""
        for separador in (";", ",", "\t", "|"):
            colunas = linha.count(separador) + 1
            if colunas > 1:
                deteccoes.append({"codificacao": codificacao, "separador": separador, "colunas": colunas})
        if deteccoes:
            break
    return deteccoes[0] if deteccoes else {"codificacao": "desconhecida", "separador": "?", "colunas": 0}


def inspecionar(url: str, *, linhas: int = 4) -> Dict[str, Any]:
    DESTINO.mkdir(parents=True, exist_ok=True)
    ficheiro = DESTINO / url.split("/")[-1]
    if not ficheiro.exists():
        with httpx.Client(timeout=None, follow_redirects=True) as cliente:
            with cliente.stream("GET", url) as resposta:
                resposta.raise_for_status()
                with ficheiro.open("wb") as saida:
                    for pedaco in resposta.iter_bytes(1 << 20):
                        saida.write(pedaco)
    resultado: Dict[str, Any] = {"zip": str(ficheiro), "bytes": ficheiro.stat().st_size, "membros": []}
    with zipfile.ZipFile(ficheiro) as zipper:
        for info in zipper.infolist():
            resultado["membros"].append({"nome": info.filename, "bytes": info.file_size, "comprimido": info.compress_size})
        dados = next((m for m in zipper.infolist() if m.filename.lower().endswith((".csv", ".txt"))), None)
        if not dados:
            return resultado
        with zipper.open(dados) as fluxo:
            amostra = fluxo.read(64 * 1024)
        leitura = detetar_leitura(amostra)
        resultado["dados"] = {"nome": dados.filename, "bytes": dados.file_size, **leitura}
        texto = amostra.decode(leitura.get("codificacao") or "utf-8", errors="replace")
        leitor = csv.reader(io.StringIO(texto), delimiter=leitura.get("separador") or ";")
        cabecalho = next(leitor, [])
        resultado["colunas"] = cabecalho
        resultado["primeiras_linhas"] = [linha for _, linha in zip(range(linhas), leitor)]
    return resultado


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspecionar o ZIP do Portal Base.")
    parser.add_argument("--ano", default="", help="Ano (por omissão, o atual)")
    parser.add_argument("--listar", action="store_true", help="Só listar os recursos")
    parser.add_argument("--linhas", type=int, default=4)
    args = parser.parse_args()

    itens = recursos()
    print(f"recursos no conjunto: {len(itens)}")
    for item in itens:
        marcador = "ZIP" if (item["formato"] or "").lower() == "zip" else "   "
        print(
            f"  {marcador} {item['titulo']:22} {str(item['formato']):6} "
            f"{(item['bytes'] or 0) / 1e6:7.1f} MB · atualizado {item['atualizado']}"
        )
    if args.listar:
        return 0

    ano = args.ano or str(max((i["ano"] for i in itens if i["formato"] == "zip" and i["ano"]), default=""))
    alvo: Optional[Dict[str, Any]] = next(
        (i for i in itens if i["ano"] == ano and (i["formato"] or "").lower() == "zip"), None
    )
    if not alvo:
        print(f"sem ZIP para o ano {ano}")
        return 1
    print(f"\n=== a inspecionar {alvo['titulo']} ({alvo['bytes'] / 1e6:.1f} MB)\n{alvo['url']}")
    resultado = inspecionar(alvo["url"], linhas=args.linhas)
    print(f"\nzip: {resultado['bytes'] / 1e6:.1f} MB")
    for membro in resultado["membros"]:
        print(f"  membro: {membro['nome']:40} {membro['bytes'] / 1e6:8.1f} MB")
    if resultado.get("dados"):
        print("\ndados:", json.dumps({k: v for k, v in resultado["dados"].items() if k != "primeiras_linhas"}, ensure_ascii=False))
        print(f"colunas ({len(resultado.get('colunas') or [])}):")
        for indice, nome in enumerate(resultado.get("colunas") or []):
            print(f"  {indice:3} {nome}")
        print("\nprimeiras linhas:")
        for linha in resultado.get("primeiras_linhas") or []:
            print(" ", json.dumps(linha[:8], ensure_ascii=False)[:220])
    return 0


if __name__ == "__main__":
    sys.exit(main())
