#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Arranca a solução FinanceLLM completa (backend FastAPI + frontend Vite).
.DESCRIPTION
    Inicia o backend uvicorn na porta FINANCE_API_PORT (padrão 8003) e o frontend
    Vite preview na porta FINANCE_UI_PORT (padrão 4180). Garante que não existem
    processos antigos dos mesmos serviços antes de arrancar.
.EXAMPLE
    .\start_solution.ps1
    .\start_solution.ps1 -ApiPort 8003 -UiPort 4180
#>
param(
    [int]$ApiPort = 8003,
    [int]$UiPort = 4180
)

$ErrorActionPreference = 'Stop'

# Cores simples para output
function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERR]  $msg" -ForegroundColor Red }

$root = 'c:\LLMFinance\finance-llm'
$venvPython = 'c:\LLMFinance\.venv\Scripts\python.exe'
$vite = "$root\chat-ui\node_modules\.bin\vite.cmd"

Set-Location $root

if ($env:FINANCE_API_PORT) { $ApiPort = [int]$env:FINANCE_API_PORT }
if ($env:FINANCE_UI_PORT) { $UiPort = [int]$env:FINANCE_UI_PORT }
Write-Info "A arrancar FinanceLLM (API:$ApiPort, UI:$UiPort)"

# 1. Limpar processos antigos
function Stop-OldProcess($namePattern, $cmdPattern) {
    Get-WmiObject Win32_Process | Where-Object {
        $_.Name -like $namePattern -and $_.CommandLine -like $cmdPattern
    } | ForEach-Object {
        Write-Warn "A terminar processo antigo PID $($_.ProcessId): $($_.CommandLine.Substring(0, [Math]::Min(80, $_.CommandLine.Length)))..."
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Stop-OldProcess 'python.exe' '*uvicorn*api.main*port*'
Stop-OldProcess 'node.exe' '*vite*preview*'
Start-Sleep -Seconds 2

# 2. Verificar dependências
if (-not (Test-Path $venvPython)) {
    Write-Err "Python do venv não encontrado: $venvPython"
    exit 1
}
if (-not (Test-Path $vite)) {
    Write-Err "vite.cmd não encontrado: $vite"
    exit 1
}

# 3. Criar logs e diretórios de dados
$logDir = "$root\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$apiLog = "$logDir\api_server_$ApiPort.log"
$uiLog = "$logDir\ui_server_$UiPort.log"

@('data/raw', 'data/processed', 'data/final', 'data/forecasting', 'data/documents/uploads', 'data/rag/markdown', 'data/rag/chunks') | ForEach-Object {
    $p = "$root\$_"
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

# 4. Arrancar backend
Write-Info "A arrancar backend em http://127.0.0.1:$ApiPort ..."
$env:PYTHONPATH = $root
$apiProc = Start-Process -FilePath $venvPython `
    -ArgumentList "-m uvicorn api.main:app --host 127.0.0.1 --port $ApiPort --workers 1 --log-level info" `
    -WorkingDirectory $root `
    -RedirectStandardOutput $apiLog `
    -RedirectStandardError "$root\logs\api_server_$ApiPort.err" `
    -WindowStyle Hidden -PassThru

# 5. Aguardar backend healthy
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 3 -ErrorAction Stop
        if ($r.status -eq 'healthy') {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $healthy) {
    Write-Err "Backend não respondeu a /health. Verifica $apiLog"
    exit 1
}
Write-Ok "Backend saudável em http://127.0.0.1:$ApiPort"

# 6. Rebuild frontend
Write-Info "A fazer build do frontend..."
Set-Location "$root\chat-ui"
$buildProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm run build' -WorkingDirectory "$root\chat-ui" -Wait -PassThru -WindowStyle Hidden
if ($buildProc.ExitCode -ne 0) {
    Write-Err "Build do frontend falhou. Verifica npm run build."
    Stop-Process -Id $apiProc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Ok "Frontend build concluído"

# 7. Arrancar frontend preview
Write-Info "A arrancar frontend em http://127.0.0.1:$UiPort ..."
$uiProc = Start-Process -FilePath $vite `
    -ArgumentList "preview --host 127.0.0.1 --port $UiPort --outDir $root\chat-ui\dist" `
    -WorkingDirectory "$root\chat-ui" `
    -RedirectStandardOutput $uiLog `
    -RedirectStandardError "$root\logs\ui_server_$UiPort.err" `
    -WindowStyle Hidden -PassThru

# 8. Aguardar frontend
$uiUp = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$UiPort" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $uiUp = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $uiUp) {
    Write-Err "Frontend não respondeu. Verifica $uiLog"
    exit 1
}
Write-Ok "Frontend disponível em http://127.0.0.1:$UiPort"

# 9. Guardar PIDs
@{
    api_pid = $apiProc.Id
    ui_pid  = $uiProc.Id
    api_port = $ApiPort
    ui_port  = $UiPort
    started_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
} | ConvertTo-Json -Depth 2 | Set-Content "$root\logs\solution_pids.json" -Encoding UTF8

Write-Host ""
Write-Ok "Solução FinanceLLM está no ar!"
Write-Info "Frontend: http://127.0.0.1:$UiPort"
Write-Info "API:      http://127.0.0.1:$ApiPort"
Write-Info "Swagger:  http://127.0.0.1:$ApiPort/docs"
Write-Info "Logs:     $logDir"
Write-Host ""
Write-Info "Para parar: .\stop_solution.ps1"
