#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Pára a solução FinanceLLM completa.
.DESCRIPTION
    Termina os processos do backend uvicorn e do frontend Vite e remove o ficheiro
    de PIDs guardado por start_solution.ps1.
#>

$ErrorActionPreference = 'SilentlyContinue'

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }

$root = 'c:\LLMFinance\finance-llm'
$pidsFile = "$root\logs\solution_pids.json"

if (Test-Path $pidsFile) {
    try {
        $state = Get-Content $pidsFile -Raw | ConvertFrom-Json -ErrorAction Stop
        if ($state.api_pid) {
            Write-Info "A terminar backend PID $($state.api_pid) ..."
            Stop-Process -Id $state.api_pid -Force
            Write-Ok "Backend terminado"
        }
        if ($state.ui_pid) {
            Write-Info "A terminar frontend PID $($state.ui_pid) ..."
            Stop-Process -Id $state.ui_pid -Force
            Write-Ok "Frontend terminado"
        }
    } catch {
        Write-Warn "Ficheiro de PIDs inválido; a procurar processos por nome..."
    }
    Remove-Item $pidsFile -Force
}

Get-WmiObject Win32_Process | Where-Object {
    ($_.Name -like 'python.exe' -and $_.CommandLine -like '*uvicorn*api.main*') -or
    ($_.Name -like 'node.exe' -and $_.CommandLine -like '*vite*preview*')
} | ForEach-Object {
    Write-Info "A terminar processo órfão PID $($_.ProcessId): $($_.Name)"
    Stop-Process -Id $_.ProcessId -Force
}

Write-Ok "Solução FinanceLLM parada"
