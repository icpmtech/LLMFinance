#!/usr/bin/env python3
"""Inspeciona a edge VM via SSH usando a chave do container iqos-origin-tunnel."""
import os
import subprocess
import tempfile
from pathlib import Path

KEY_CONTAINER = "iqos-origin-tunnel"
KEY_PATH_IN_CONTAINER = "/key/id_ed25519"
VM_HOST = "45.147.251.188"
VM_USER = "root"


def fetch_key() -> Path:
    tmp = tempfile.mkdtemp(prefix="edge_key_")
    key_file = Path(tmp) / "id_ed25519"
    subprocess.run(
        ["docker", "cp", f"{KEY_CONTAINER}:{KEY_PATH_IN_CONTAINER}", str(key_file)],
        check=True,
    )
    # Windows não tem chmod 600 facilmente; ssh no Windows/OpenSSH exige permissões restritas.
    # Usamos icacls para remover todos exceto o owner.
    import platform

    if platform.system() == "Windows":
        subprocess.run(
            ["icacls", str(key_file), "/inheritance:r", "/remove", "BUILTIN\\Users", "Everyone", "NT AUTHORITY\\Authenticated Users"],
            check=False,
        )
        subprocess.run(["icacls", str(key_file), "/grant", f"{os.environ.get('USERNAME', 'USERS')}:R"], check=False)
    else:
        key_file.chmod(0o600)
    return key_file


def run_ssh(key_file: Path, command: str) -> tuple[str, str, int]:
    args = [
        "ssh",
        "-i", str(key_file),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=8",
        f"{VM_USER}@{VM_HOST}",
        command,
    ]
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.stdout, proc.stderr, proc.returncode


def run_one(key_file: Path, cmd: str, label: str) -> None:
    print(f"\n=== {label} ===")
    try:
        stdout, stderr, rc = run_ssh(key_file, cmd)
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
        return
    print(f"exit={rc}")
    if stdout:
        print("STDOUT:")
        print(stdout.rstrip())
    if stderr:
        print("STDERR:")
        print(stderr.rstrip())


def main() -> None:
    key_file = fetch_key()
    print(f"Chave: {key_file}")
    run_one(key_file, "hostname; id", "basic info")
    run_one(key_file, "docker ps --format '{{{{.Names}}}}|{{{{.Ports}}}}|{{{{.Status}}}}'", "docker containers")


if __name__ == "__main__":
    main()
