@echo off
cd /d c:\LLMFinance\finance-llm
set PYTHONUNBUFFERED=1
c:\LLMFinance\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8002 --workers 1 --log-level info >> c:\LLMFinance\finance-llm\logs\api_8002_live.log 2>&1
