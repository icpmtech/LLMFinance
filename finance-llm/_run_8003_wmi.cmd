@echo off
cd /d C:\LLMFinance\finance-llm
call .venv\Scripts\activate.bat
python -m uvicorn api.main:app --host 127.0.0.1 --port 8003 --workers 1 --log-level info >> C:\LLMFinance\finance-llm\logs\api_server_8003_providers.log 2>&1
