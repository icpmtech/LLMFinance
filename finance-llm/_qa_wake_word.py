"""Valida a palavra de ativação «sabemos» com **áudio real**, pela rota do chat.

Gera (fora daqui, com a voz do Windows) um WAV com «sabemos …» e outro sem a
palavra, envia ambos a `POST /jarvis/wake` e confirma que a palavra é detetada no
primeiro e não no segundo. É a única forma de validar a deteção sem um microfone:
a transcrição decide, e é ela que acorda o chat.

    python _qa_wake_word.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

API = "http://127.0.0.1:8002"
POSITIVO = Path("_qa_wake_sabemos.wav")
CONTROLO = Path("_qa_wake_controlo.wav")


def _enviar(caminho: Path) -> dict:
    with caminho.open("rb") as ficheiro:
        return httpx.post(
            f"{API}/jarvis/wake",
            params={"language": "pt"},
            files={"audio": (caminho.name, ficheiro, "audio/wav")},
            timeout=180.0,
        ).json()


def main() -> int:
    falhas = 0

    voz = httpx.get(f"{API}/jarvis/voice", timeout=60.0).json()
    wake = voz.get("wake") or {}
    print(f"motor: {wake.get('engine')} | modelo: {wake.get('model')} | disponivel: {wake.get('available')}")
    print(f"palavras: {wake.get('words')}")
    if wake.get("available"):
        print("OK  escuta contínua disponível (o botão da orelha fica ativo)")
    else:
        print(f"X   escuta contínua indisponível: {wake.get('note')}")
        falhas += 1

    for caminho, esperado in ((POSITIVO, True), (CONTROLO, False)):
        if not caminho.exists():
            print(f"X   falta o áudio {caminho}")
            falhas += 1
            continue
        resultado = _enviar(caminho)
        ativo = bool(resultado.get("active"))
        marca = "OK " if ativo is esperado else "X  "
        print(f"{marca} {caminho.name}: active={ativo} palavra={resultado.get('word')!r}")
        print(f"     ouvido: {resultado.get('text')!r}")
        print(f"     comando: {resultado.get('command')!r}")
        if ativo is not esperado:
            falhas += 1
        if esperado and not str(resultado.get("command") or "").strip():
            print("X   a palavra foi ouvida mas não veio pedido atrás dela")
            falhas += 1

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
