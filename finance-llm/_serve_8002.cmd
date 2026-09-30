@echo off
cd /d c:\LLMFinance\finance-llm
c:\LLMFinance\.venv\Scripts\uvicorn.exe api.main:app --host 127.0.0.1 --port 8002 --app-dir c:\LLMFinance\finance-llm > c:\LLMFinance\finance-llm\logs\api_8002.log 2>&1
