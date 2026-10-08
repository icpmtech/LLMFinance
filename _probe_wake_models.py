"""Qual é o melhor modelo/prompt para ouvir a palavra de ativação em pt-PT?

Testa `tiny` e `base`, com e sem `initial_prompt` (enviesamento do descodificador
para as palavras de ativação), medindo latência e acerto. O áudio é gerado com o
`edge-tts` (voz Raquel), para o teste ser reprodutível sem microfone.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from api import jarvis_service as js

FRASES = [
    "Jarvis, quantos contratos tem a EDP?",
    "Hey Jarvis, abre as insolvências.",
    "Apollo, qual é o maior contrato de energia?",
    "Bom dia, está tudo bem?",
]
PROMPT = "Jarvis, hey Jarvis, Apollo, hey Hermes."


def sintetizar(texto: str) -> bytes:
    audio, _ = asyncio.run(js.synthesize(texto, voice="pt-PT-RaquelNeural"))
    return audio


def transcrever(mp3: bytes, modelo: str, prompt: str | None) -> tuple[str, float]:
    from faster_whisper import WhisperModel

    handle, path = tempfile.mkstemp(suffix=".mp3", prefix="wake-")
    import os

    os.close(handle)
    Path(path).write_bytes(mp3)
    try:
        whisper = js._whisper_model(WhisperModel, modelo)
        started = time.perf_counter()
        segments, _ = whisper.transcribe(
            path, language="pt", vad_filter=True, initial_prompt=prompt
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text, (time.perf_counter() - started) * 1000
    finally:
        os.unlink(path)


def main() -> int:
    audios = [(frase, sintetizar(frase)) for frase in FRASES]
    print("áudio gerado:", [(f[:28], len(a) // 1024) for f, a in audios])

    for modelo in ("tiny", "base"):
        for prompt in (None, PROMPT):
            print(f"\n=== modelo={modelo} prompt={'sim' if prompt else 'não'} ===")
            acertos = 0
            tempos = []
            for frase, mp3 in audios:
                texto, ms = transcrever(mp3, modelo, prompt)
                tempos.append(ms)
                match = js.match_wake(texto)
                esperado = js.match_wake(frase)["active"]
                ok = match["active"] == esperado
                acertos += 1 if ok else 0
                print(
                    f"  {'ok  ' if ok else 'ERRO'} esperado={esperado!s:<5} "
                    f"obtido={match['active']!s:<5} {mensagem(texto, match)}  [{ms:.0f} ms]"
                )
            print(f"  acertos: {acertos}/{len(audios)} | mediana {sorted(tempos)[len(tempos) // 2]:.0f} ms")
    return 0


def mensagem(texto: str, match: dict) -> str:
    if match["active"]:
        return f"«{texto}» → {match['word']!r} + comando {match['command']!r}"
    return f"«{texto}»"


if __name__ == "__main__":
    sys.exit(main())
