import subprocess
import os
import sys
import time

env = os.environ.copy()
env['PYTHONUNBUFFERED'] = '1'
env['ELASTICSEARCH_URL'] = 'http://127.0.0.1:9200'
env['TWOCAPTCHA_API_KEY'] = '603223f68a8474f3a9531cddce3e1d6c'

# Ensure the venv interpreter is found by any subprocess spawned by uvicorn.
env['PATH'] = r'c:\LLMFinance\.venv\Scripts;' + env.get('PATH', '')
env['VIRTUAL_ENV'] = r'c:\LLMFinance\.venv'

log_out = r'c:/LLMFinance/finance-llm/logs/api_dashboard_contratos_es.out'
log_err = r'c:/LLMFinance/finance-llm/logs/api_dashboard_contratos_es.err'

with open(log_out, 'w') as out, open(log_err, 'w') as err:
    proc = subprocess.Popen(
        [r'c:/LLMFinance/.venv/Scripts/uvicorn.exe', 'api.main:app',
         '--host', '127.0.0.1', '--port', '8002',
         '--app-dir', 'c:/LLMFinance/finance-llm'],
        cwd=r'c:/LLMFinance/finance-llm',
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=0x00000008,
    )
    print('launcher pid', os.getpid())
    print('uvicorn pid', proc.pid)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
