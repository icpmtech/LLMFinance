"""Script único de arranque para o IQ OS.

Inicia o backend FastAPI (porta 8001) e o frontend Vite (porta 5173),
utilizando o ambiente virtual e o node_modules existentes. Ao terminar
(ctrl+c) os processos filhos são encerrados.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
NPM = "npm.cmd" if sys.platform == "win32" else "npm"

API_HOST = os.getenv("FINANCE_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("FINANCE_API_PORT", "8002"))
UI_PORT = int(os.getenv("FINANCE_UI_PORT", "5174"))


def die(msg: str) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def wait_for_port(host: str, port: int, timeout: float = 60.0, label: str = "") -> bool:
    import socket
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if label:
            remaining = int(deadline - time.time())
            if remaining % 10 == 0:
                print(f"[start] A aguardar {label}... ({remaining}s restantes)", end="\r")
        try:
            with socket.create_connection((host, port), timeout=1.0):
                if label:
                    print(f"[start] {label} respondeu.")
                return True
        except OSError:
            time.sleep(0.5)
    if label:
        print()
    return False


def kill_existing_on_port(port: int) -> None:
    """Termina processos que estejam a escutar numa porta local (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import subprocess as _subprocess

        output = _subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            errors="ignore",
        )
        pids = set()
        for line in output.splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            # Local address normalmente é o segundo campo; PID o último.
            if len(parts) >= 5 and parts[1].endswith(f":{port}"):
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
        for pid in pids:
            try:
                _subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            except Exception:
                pass
        if pids:
            time.sleep(1.0)
    except Exception:
        pass


def main() -> None:
    if not PYTHON.exists():
        die(f"Ambiente virtual não encontrado: {PYTHON}")

    node_modules = ROOT / "chat-ui" / "node_modules"
    if not node_modules.exists():
        die("node_modules não encontrado. Executa 'cd chat-ui && npm install' primeiro.")

    use_dev = os.getenv("FINANCE_UI_DEV", "0") == "1"
    if use_dev:
        ui_cmd = [NPM, "run", "dev", "--", "--port", str(UI_PORT), "--host", "127.0.0.1"]
    else:
        dist = ROOT / "chat-ui" / "dist"
        if not dist.exists():
            die("Build do UI não encontrada. Executa 'cd chat-ui && npm run build' primeiro.")
        ui_cmd = [NPM, "run", "preview", "--", "--port", str(UI_PORT), "--host", "127.0.0.1", "--strictPort"]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["NODE_ENV"] = "development" if use_dev else "production"

    api_cmd = [
        str(PYTHON),
        "-m",
        "uvicorn",
        "api.main:app",
        "--host",
        API_HOST,
        "--port",
        str(API_PORT),
    ]

    print(f"[start] A iniciar backend em http://{API_HOST}:{API_PORT}")
    kill_existing_on_port(API_PORT)
    api_proc = subprocess.Popen(
        api_cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    if not wait_for_port(API_HOST, API_PORT, timeout=60.0, label="backend"):
        api_proc.terminate()
        die("Backend não respondeu dentro do tempo limite.")
    print(f"[start] Backend OK")

    print(f"[start] A iniciar frontend em http://127.0.0.1:{UI_PORT}")
    kill_existing_on_port(UI_PORT)
    ui_proc = subprocess.Popen(
        ui_cmd,
        cwd=ROOT / "chat-ui",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    ui_timeout = float(os.getenv("FINANCE_UI_TIMEOUT", "180"))
    if not wait_for_port("127.0.0.1", UI_PORT, timeout=ui_timeout, label="frontend"):
        ui_proc.terminate()
        api_proc.terminate()
        die("Frontend não respondeu dentro do tempo limite.")
    print(f"[start] Frontend OK")
    print(f"[start] Aplicação pronta: http://127.0.0.1:{UI_PORT}")
    print("[start] Pressiona Ctrl+C para parar ambos os serviços.\n")

    def pump(proc: subprocess.Popen, prefix: str) -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                if line:
                    print(f"[{prefix}] {line.rstrip()}")
        except Exception:
            pass

    try:
        api_thread = threading.Thread(target=pump, args=(api_proc, "API"), daemon=True)
        ui_thread = threading.Thread(target=pump, args=(ui_proc, "UI"), daemon=True)
        api_thread.start()
        ui_thread.start()

        while True:
            time.sleep(1.0)
            if api_proc.poll() is not None:
                raise RuntimeError(f"API terminou com código {api_proc.poll()}")
            if ui_proc.poll() is not None:
                raise RuntimeError(f"UI terminou com código {ui_proc.poll()}")
    except KeyboardInterrupt:
        print("\n[start] A interromper serviços...")
    finally:
        for proc, name in [(api_proc, "API"), (ui_proc, "UI")]:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
            print(f"[start] {name} parado.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        die(str(exc))
