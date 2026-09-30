@echo off
cd /d c:\LLMFinance\finance-llm
set PYTHONUNBUFFERED=1
set ELASTICSEARCH_URL=http://127.0.0.1:9200
c:\LLMFinance\.venv\Scripts\uvicorn.exe api.main:app --host 127.0.0.1 --port 8002 --app-dir c:/LLMFinance/finance-llm >> c:\LLMFinance\finance-llm\logs\_api_devedores.out 2>&1
