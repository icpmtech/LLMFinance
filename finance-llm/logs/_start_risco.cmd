@echo off
cd /d c:\LLMFinance\finance-llm
set PYTHONUNBUFFERED=1
"c:\LLMFinance\.venv\Scripts\python.exe" -m uvicorn api.main:app --host 127.0.0.1 --port 8002 --app-dir c:/LLMFinance/finance-llm >> "c:\LLMFinance\finance-llm\logs\_risco_8002.log" 2>&1
