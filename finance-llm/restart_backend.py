import subprocess
import os
import signal
import sys
import time

# Kill existing python processes running uvicorn for this app
import psutil
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.info['name'] == 'python.exe' and proc.info['cmdline'] and 'api.main:app' in ' '.join(proc.info['cmdline']):
            print(f"Killing old backend pid={proc.info['pid']}")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

env = os.environ.copy()
env['PYTHONPATH'] = r'c:\LLMFinance\finance-llm'
env['FINANCE_API_PORT'] = '8003'

cwd = r'c:\LLMFinance\finance-llm'
log_path = os.path.join(cwd, 'logs', 'api_server_8003_new.log')

print("Starting backend...")
with open(log_path, 'wb') as log:
    proc = subprocess.Popen(
        [r'c:\LLMFinance\.venv\Scripts\python.exe', '-m', 'uvicorn', 'api.main:app',
         '--host', '127.0.0.1', '--port', '8003', '--workers', '1', '--log-level', 'info'],
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    print(f"Backend started pid={proc.pid}, log={log_path}")
