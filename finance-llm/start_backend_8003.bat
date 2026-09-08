@echo off
setlocal
if not defined FINANCE_API_PORT set FINANCE_API_PORT=8003
set PYTHONPATH=c:\LLMFinance\finance-llm
cd /d c:\LLMFinance\finance-llm
c:\LLMFinance\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port %FINANCE_API_PORT% --workers 1 --log-level info > api_server_%FINANCE_API_PORT%.log 2>&1
if errorlevel 1 (
    echo Backend failed, see api_server_%FINANCE_API_PORT%.log
    pause
)
