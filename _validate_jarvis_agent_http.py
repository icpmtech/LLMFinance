"""Valida o Jarvis pela API: gateway do agente + voz pt-PT no servidor.

Corre contra o backend (por omissão `http://127.0.0.1:8002`), esperando pelo
`/health` primeiro. Confirma:

* `/jarvis/meta` — quatro gateways, bloco `agent` com skills/capacidades, TTS `edge-tts`;
* `/jarvis/tools?gateway=agent` — as três ferramentas de delegação;
* `/jarvis/voice` — motor de síntese e vozes pt-PT;
* `/jarvis/speak` — MP3 real com `pt-PT-RaquelNeural` e `pt-PT-DuarteNeural`.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("JARVIS_BASE", "http://127.0.0.1:8002")


def wait_health(timeout: float = 420.0) -> bool:
    started = time.time()
    while time.time() - started < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=5) as resp:
                if resp.status == 200:
                    print(f"/health ok em {time.time() - started:.0f}s")
                    return True
        except Exception:
            time.sleep(5)
    return False


def post(path: str, payload: dict, *, raw: bool = False):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
        if raw:
            return data, resp.headers.get("Content-Type", "")
        return json.loads(data.decode("utf-8"))


def main() -> int:
    failures: list[str] = []
    if not wait_health():
        print("FALHA: o backend não respondeu em /health")
        return 1

    with urllib.request.urlopen(f"{BASE}/jarvis/meta", timeout=60) as resp:
        meta = json.loads(resp.read().decode("utf-8"))

    gateways = {entry["id"]: entry for entry in meta["gateways"]}
    print("gateways:", {k: v["tools"] for k, v in gateways.items()})
    if set(gateways) != {"hermes", "agent", "mcp", "web"}:
        failures.append(f"gateways inesperados: {sorted(gateways)}")

    agent = meta.get("agent") or {}
    print("agente:", {k: agent.get(k) for k in ("available", "version", "model", "toolsets", "skills")})
    if not agent.get("available"):
        failures.append(f"agente não disponível: {agent.get('error')}")
    if not agent.get("skills"):
        failures.append("o agente não reportou skills")

    tts = meta["voice"]["tts"]
    print("tts:", tts["engine"], "| vozes:", [v["id"] for v in tts["voices"]][:3])
    if tts["engine"] != "edge-tts":
        failures.append(f"motor de síntese inesperado: {tts['engine']}")

    with urllib.request.urlopen(f"{BASE}/jarvis/tools?gateway=agent", timeout=30) as resp:
        tools = json.loads(resp.read().decode("utf-8"))
    ids = {item["id"] for item in (tools.get("tools") or tools)}
    print("ferramentas do agente:", sorted(ids))
    if ids != {"agent.ask", "agent.skills", "agent.capabilities"}:
        failures.append(f"ferramentas do agente inesperadas: {sorted(ids)}")

    with urllib.request.urlopen(f"{BASE}/jarvis/voice", timeout=30) as resp:
        voice = json.loads(resp.read().decode("utf-8"))
    print("voz:", voice.get("tts", {}).get("engine"), "| predefinida:", voice.get("tts", {}).get("default_voice"))

    for name in ("pt-PT-RaquelNeural", "pt-PT-DuarteNeural"):
        audio, content_type = post("/jarvis/speak", {"text": "Bom dia, sou o Jarvis.", "voice": name}, raw=True)
        header = audio[:3]
        print(f"speak {name}: {len(audio)} bytes | {content_type} | header={header!r}")
        if len(audio) < 5000 or header[0] != 0xFF:
            failures.append(f"áudio inválido para {name} ({len(audio)} bytes)")

    print("\n=== resultado ===")
    for failure in failures:
        print("FALHA:", failure)
    if failures:
        return 1
    print("OK: gateway do Hermes Agent + voz pt-PT no servidor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
