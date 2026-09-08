$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'c:\LLMFinance\finance-llm'
$port = if ($env:FINANCE_API_PORT) { $env:FINANCE_API_PORT } else { '8003' }
Set-Location 'c:\LLMFinance\finance-llm'
& 'c:\LLMFinance\.venv\Scripts\python.exe' -m uvicorn api.main:app --host 127.0.0.1 --port $port --workers 1 --log-level info
