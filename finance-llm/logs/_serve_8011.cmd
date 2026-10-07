@echo off
rem Servidor local (codigo em disco, sem passar pelo Docker) para testar a
rem Pesquisa profunda com as alteracoes mais recentes. Porta 8011 para nao
rem colidir com o contentor, que publica 8002.
rem Arrancar por WMI para nao morrer com o terminal.
setlocal
cd /d C:\LLMFinance\finance-llm
set PYTHONIOENCODING=utf-8
"C:\LLMFinance\.venv\Scripts\python.exe" -m uvicorn api.main:app --host 127.0.0.1 --port 8011 >> logs\_serve_8011.log 2>&1
