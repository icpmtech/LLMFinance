# Atalho do CLI do IQ OS (PowerShell).
#
# Uso:
#   .\finance-llm.ps1 status
#   .\finance-llm.ps1 auth login nome@empresa.pt
#   .\finance-llm.ps1 contracts search "obras de reabilitação" --year 2025
#
# Se o PowerShell bloquear a execução de scripts, use:
#   powershell -ExecutionPolicy Bypass -File .\finance-llm.ps1 status

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$candidates = @(
    (Join-Path $root ".venv\Scripts\python.exe"),
    (Join-Path $root "..\.venv\Scripts\python.exe")
)
$python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) { $python = "python" }

Push-Location $root
try {
    & $python -m cli @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
