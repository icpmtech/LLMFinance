"""Palavra de ativação: tolerância fonética + transcrição local (5 passagens).

O `tiny` não é determinístico: a mesma fala vira «Jarvis» ou «Jervis». Aqui
verifica-se que o comparador aceita as variações plausíveis e recusa as que não
são a palavra de ativação, e mede-se o acerto em passagens reais pelo whisper.
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter

from api import jarvis_service as js

# (texto transcrito, deve ativar?)
CASOS = [
    ("Jarvis, quantos contratos tem a EDP?", True),
    ("Jervis, quantos contratos tem a EDP?", True),  # variação real do tiny
    ("Harvis, abre as insolvências", True),
    ("Jarbis, qual é o maior contrato?", True),
    ("hey jarvis abre as insolvências", True),
    ("Apollo, qual é o maior contrato de energia?", True),
    ("Apolo, qual é o maior contrato de energia?", True),
    ("hey hermes, resume isto", True),
    ("JARVIS", True),
    ("Olá, Jarvis", True),
    ("boa tarde, tudo bem?", False),
    ("o jarvison disse aquilo", False),
    ("o serviço público de saúde", False),
    ("a gravir, abre as insolvências", False),
    ("há vários contratos", False),
]

FALA = ["Jarvis, quantos contratos tem a EDP?", "Bom dia, está tudo bem?"]
REPETICOES = 5


def main() -> int:
    print("palavras:", js.WAKE_WORDS)
    print("modelo:", js.WAKE_MODEL, "| prompt:", js.WAKE_PROMPT[:70])

    falhas = 0
    print("\n=== comparador ===")
    for texto, esperado in CASOS:
        r = js.match_wake(texto)
        ok = r["active"] == esperado
        falhas += 0 if ok else 1
        print(
            f"{'ok  ' if ok else 'ERRO'} esperado={esperado!s:<5} {texto!r} -> "
            f"{r['active']} {r['word']} {r['command']!r}"
        )

    print(f"\n=== transcrição a sério ({REPETICOES}× por frase) ===")
    for frase in FALA:
        audio, _ = asyncio.run(js.synthesize(frase, voice="pt-PT-RaquelNeural"))
        esperado = js.match_wake(frase)["active"]
        vistos: Counter = Counter()
        tempos = []
        for _ in range(REPETICOES):
            r = js.transcribe_wake(audio, filename="fala.mp3", language="pt")
            vistos[(r["active"], r["text"])] += 1
            tempos.append(r["elapsed_ms"])
        acertos = sum(quantos for (active, _), quantos in vistos.items() if active == esperado)
        print(
            f"\nfrase: {frase!r} (ativar={esperado}) -> {acertos}/{REPETICOES} acertos "
            f"| mediana {sorted(tempos)[len(tempos) // 2]} ms"
        )
        for (active, texto), quantos in vistos.most_common():
            print(f"   {quantos}× active={active}: {texto!r}")
        if acertos < REPETICOES:
            falhas += 1

    print("\n=== resultado ===")
    print("falhas:", falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
