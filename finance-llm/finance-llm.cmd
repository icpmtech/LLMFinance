@echo off
rem Atalho do CLI do FinanceLLM (Windows).
rem Uso: finance-llm.cmd status | auth login <email> | contracts search "obras"
setlocal
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
  set "PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%..\.venv\Scripts\python.exe" (
  set "PY=%SCRIPT_DIR%..\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
"%PY%" -m cli %*
exit /b %ERRORLEVEL%
