#!/usr/bin/env python3
"""Inspeciona a edge VM via SSH usando paramiko e a chave do container."""
import os
import subprocess
import tempfile
from pathlib import Path

import paramiko

KEY_CONTAINER = "iqos-origin-tunnel"
KEY_PATH_IN_CONTAINER = "/key/id_ed25519"
VM_HOST = "45.147.251.188"
VM_USER = "root"


def fetch_key() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="edge_key_"))
    key_file = tmp / "id_ed25519"
    subprocess.run(
        ["docker", "cp", f"{KEY_CONTAINER}:{KEY_PATH_IN_CONTAINER}", str(key_file)],
        check=True,
    )
    if os.name == "nt":
        # Windows: remove all ACEs except current user read.
        subprocess.run(["icacls", str(key_file), "/inheritance:r", "/grant", f"{os.environ['USERNAME']}:R"], check=True, capture_output=True)
        subprocess.run(["icacls", str(key_file), "/remove", "BUILTIN\\Users", "Everyone", "NT AUTHORITY\\Authenticated Users"], check=False, capture_output=True)
    else:
        key_file.chmod(0o600)
    return key_file


def run_ssh_command(cmd: str) -> str:
    key_file = fetch_key()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VM_HOST, username=VM_USER, key_filename=str(key_file), timeout=10, banner_timeout=10, auth_timeout=10)
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return f"exit={rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}"
    finally:
        client.close()


def main() -> None:
    commands = [
        ("hostname; id; uname -a", "basic info"),
        ("docker ps --format '{{.Names}}|{{.Ports}}|{{.Status}}'", "docker containers"),
        ("docker exec caddy cat /etc/caddy/Caddyfile 2>/dev/null || true", "caddy Caddyfile via name"),
        ("docker exec $(docker ps -q -f name=caddy | head -1) cat /etc/caddy/Caddyfile 2>/dev/null || true", "caddy Caddyfile via id"),
        ("find /etc /opt /root /var -maxdepth 3 -name Caddyfile 2>/dev/null | head -20", "find Caddyfile"),
        ("ls -la /opt /root /home 2>/dev/null | head -40", "directories"),
    ]
    for cmd, label in commands:
        print(f"\n=== {label} ===")
        try:
            print(run_ssh_command(cmd))
        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == "__main__":
    main()
