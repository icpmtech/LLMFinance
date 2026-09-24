"""Lista processos relevantes e tarefas agendadas para `_probe_procs.json`.

Serve para descobrir quem anda a lançar sincronizações de contribuintes:
procura processos de Python/PowerShell com `contribuintes` ou `sync` na linha de
comando (e as respetivas cadeias de pais).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "_probe_procs.json"


def ps(command: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def main() -> int:
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine | "
        "ConvertTo-Json -Depth 3 -Compress"
    )
    raw = ps(script).strip()
    try:
        processes = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        processes = []
    if isinstance(processes, dict):
        processes = [processes]

    interesting = []
    for proc in processes:
        command = (proc.get("CommandLine") or "").lower()
        name = (proc.get("Name") or "").lower()
        if not name.startswith(("python", "powershell", "pwsh", "cmd")):
            continue
        if any(word in command for word in ("_sync_contribuintes", "contribuintes", "sync_", "while", "for (")):
            interesting.append(
                {
                    "pid": proc.get("ProcessId"),
                    "parent": proc.get("ParentProcessId"),
                    "name": proc.get("Name"),
                    "started": proc.get("CreationDate"),
                    "cmd": (proc.get("CommandLine") or "")[:400],
                }
            )

    tasks = ps("schtasks /query /fo LIST /v | Select-String -Pattern 'contribuintes' -SimpleMatch")
    payload = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "processes": interesting,
        "tasks": [line.strip() for line in tasks.splitlines() if line.strip()][:20],
        "python_total": sum(1 for p in processes if (p.get("Name") or "").lower().startswith("python")),
        "running_syncs": [
            {
                "pid": p.get("ProcessId"),
                "parent": p.get("ParentProcessId"),
                "started": p.get("CreationDate"),
                "cmd": (p.get("CommandLine") or "")[:200],
            }
            for p in processes
            if "_sync_contribuintes" in (p.get("CommandLine") or "").lower()
        ],
    }
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"escrito {TARGET.name}: {len(interesting)} processos, {len(payload['running_syncs'])} sincronizações")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
