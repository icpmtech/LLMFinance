@echo off
rem Gerado por backfill.ps1 - alteracoes a mao perdem-se.
cd /d C:\LLMFinance\finance-llm
set PYTHONIOENCODING=utf-8
set TOKENIZERS_PARALLELISM=false
"C:\LLMFinance\.venv\Scripts\python.exe" "C:\LLMFinance\finance-llm\logs\_backfill_contratos_v2.py" --workers 6 --threads 2 --por-ano >> "C:\LLMFinance\finance-llm\logs\_backfill_run.log" 2>&1
echo ==== fim %DATE% %TIME% (codigo %ERRORLEVEL%) ==== >> "
C:\LLMFinance\finance-llm\logs\_backfill_run.log
"