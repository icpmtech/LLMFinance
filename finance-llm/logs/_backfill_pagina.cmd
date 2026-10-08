@echo off
rem Pagina web de acompanhamento do backfill (http://127.0.0.1:8013).
rem Arrancar pelo WMI para nao morrer quando o terminal fecha:
rem   Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
rem     CommandLine='cmd.exe /c C:\LLMFinance\finance-llm\logs\_backfill_pagina.cmd';
rem     CurrentDirectory='C:\LLMFinance\finance-llm' }
setlocal
cd /d C:\LLMFinance\finance-llm
set PYTHONIOENCODING=utf-8
"C:\LLMFinance\.venv\Scripts\python.exe" -u logs\backfill_pagina.py >> logs\_backfill_pagina.log 2>&1
