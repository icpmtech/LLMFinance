@echo off
rem Pagina web de acompanhamento do backfill (http://127.0.0.1:8013).
rem Arrancar pelo WMI para nao morrer quando o terminal fecha:
rem   Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
rem     CommandLine='cmd.exe /c C:\LLMFinance\finance-llm\logs\_backfill_pagina.cmd';
rem     CurrentDirectory='C:\LLMFinance\finance-llm' }
setlocal
cd /d C:\LLMFinance\finance-llm
set PYTHONIOENCODING=utf-8
:volta
rem Se ja houver alguem a escutar na porta (instancia antiga, ou um arranque que
rem ficou orfao), espera em vez de arrancar uma segunda: duas instancias a lutar
rem pela mesma porta enchem o log de tracebacks.
netstat -ano | findstr /C:"LISTENING" | findstr /C:":8013 " > nul || goto arrancar
ping -n 6 127.0.0.1 > nul
goto volta

:arrancar
rem Se o Python morrer (erro nao tratado, ES a cair, maquina com pouca memoria)
rem o ciclo volta a arranca-lo, em vez de deixar a porta 8013 sem ninguem a escutar.
rem Nota: o python.exe do .venv e um lancador -- cria o interprete real como filho,
rem por isso ha sempre dois processos python por cada instancia da pagina.
echo [%date% %time%] a arrancar a pagina do backfill >> logs\_backfill_pagina.log
"C:\LLMFinance\.venv\Scripts\python.exe" -u logs\backfill_pagina.py >> logs\_backfill_pagina.log 2>&1
echo [%date% %time%] a pagina terminou (codigo %errorlevel%) - a repetir >> logs\_backfill_pagina.log
rem `ping` em vez de `timeout`: o `timeout` falha sem consola de entrada (WMI).
ping -n 6 127.0.0.1 > nul
goto volta
