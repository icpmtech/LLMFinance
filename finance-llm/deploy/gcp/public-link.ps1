#requires -Version 5.1
<#
.SYNOPSIS
    Publica a stack local do IQ OS num link Cloudflare e impede o PC de hibernar
    enquanto o link estiver a correr.

.DESCRIPTION
    Arranca o cloudflared num processo destacado (não morre quando fechas o
    terminal) e mantém o sistema acordado com SetThreadExecutionState, que liga o
    bloqueio de suspensão/hibernação **só enquanto este processo viver**.

    Duas variantes de link:
      * quick tunnel (por omissão) — link novo https://<aleatorio>.trycloudflare.com,
        não precisa de domínio nem de conta Cloudflare. Muda a cada arranque.
      * túnel nomeado (-ConfigPath) — link fixo do teu domínio, com Access, se
        tiveres corrido o 01-setup-tunnels.ps1.

.PARAMETER Origin
    Onde a stack local responde. Por omissão http://127.0.0.1:4180 (nginx do
    docker compose: serve a SPA e faz proxy de /api/ para o backend).

.PARAMETER ConfigPath
    Config de um túnel nomeado (deploy/gcp/origin/config.yml). Se indicado, o
    link é o hostname público dessa config, em vez de um quick tunnel.

.PARAMETER SetPowerTimeouts
    Além do SetThreadExecutionState, põe os timeouts de suspensão/hibernação em
    "nunca" no plano de energia ativo (powercfg). É persistente e pode precisar
    de PowerShell como Administrador.

.PARAMETER Stop
    Pára o link e liberta o bloqueio de suspensão.

.EXAMPLE
    .\public-link.ps1
.EXAMPLE
    .\public-link.ps1 -ConfigPath .\origin\config.yml
.EXAMPLE
    .\public-link.ps1 -Stop
#>
[CmdletBinding()]
param(
    [string]$Origin = 'http://127.0.0.1:4180',
    [string]$ConfigPath,
    [switch]$SetPowerTimeouts,
    [switch]$Stop,
    [switch]$Worker
)

$ErrorActionPreference = 'Stop'

$workDir   = $PSScriptRoot
$urlFile   = Join-Path $workDir 'public-link.txt'
$logFile   = Join-Path $workDir 'public-link.log'
$errFile   = Join-Path $workDir 'public-link.err.log'
$pidFile   = Join-Path $workDir 'public-link.pid'

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }
function Write-Bad([string]$Text) { Write-Host "    XX  $Text" -ForegroundColor Red }

# Impede a suspensão/hibernação por inatividade enquanto esta thread viver.
if (-not ('Win32.Power' -as [type])) {
    Add-Type -Namespace Win32 -Name Power -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
}
# Nota: `0x80000000` em PS 5.1 é um Int32 negativo e não converte para UInt32 —
# daí o sufixo `L` (long), cujo valor positivo cabe em UInt32.
$ES_CONTINUOUS       = [uint32]0x80000000L
$ES_SYSTEM_REQUIRED  = [uint32]0x00000001L
$ES_AWAKE            = $ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED

function Get-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cmd) { throw 'cloudflared não está no PATH (winget install Cloudflare.cloudflared).' }
    return $cmd.Source
}

function Get-RunningProcesses {
    $r = [ordered]@{ Worker = $null; Tunnel = $null }
    if (Test-Path $pidFile) {
        $lines = @(Get-Content -LiteralPath $pidFile | Where-Object { $_ -match '^\d+' })
        foreach ($line in $lines) {
            $parts = $line -split '\|'
            $p = Get-Process -Id ([int]$parts[1]) -ErrorAction SilentlyContinue
            if ($p) { $r[$parts[0]] = $p }
        }
    }
    return $r
}

# ---------------------------------------------------------------------------
# Parar
# ---------------------------------------------------------------------------
if ($Stop) {
    Write-Step 'Parar o link público'
    $running = Get-RunningProcesses
    if (-not $running.Worker -and -not $running.Tunnel) {
        Write-Warn2 'Não havia nada a correr.'
    }
    foreach ($k in @('Tunnel', 'Worker')) {
        $p = $running[$k]
        if ($p) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Write-Ok "parado: $k (PID $($p.Id))"
        }
    }
    [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS)  # liberta o bloqueio
    Remove-Item -LiteralPath $pidFile, $urlFile -ErrorAction SilentlyContinue
    Write-Ok 'Bloqueio de suspensão libertado.'
    return
}

# ---------------------------------------------------------------------------
# Worker: corre o cloudflared e mantém o PC acordado (processo destacado)
# ---------------------------------------------------------------------------
if ($Worker) {
    $cf = Get-Cloudflared
    $cfArgs = if ($ConfigPath) { @('tunnel', '--no-autoupdate', '--config', $ConfigPath, 'run') }
              else { @('tunnel', '--no-autoupdate', '--url', $Origin) }

    Remove-Item -LiteralPath $logFile, $errFile, $urlFile -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $cf -ArgumentList $cfArgs -NoNewWindow -PassThru `
        -RedirectStandardOutput $logFile -RedirectStandardError $errFile

    "Worker|$PID`nTunnel|$($proc.Id)" | Set-Content -LiteralPath $pidFile -Encoding ASCII

    # O cloudflared escreve o URL no log de erro (logrus -> stderr).
    $deadline = (Get-Date).AddSeconds(90)
    $url = $null
    while (-not $url -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        if ($proc.HasExited) { break }
        if (Test-Path $errFile) {
            $txt = Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue
            if ($txt -match '(https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com)') { $url = $Matches[1] }
        }
        if (-not $url -and $ConfigPath) {
            $txt = Get-Content -LiteralPath $ConfigPath -Raw -ErrorAction SilentlyContinue
            if ($txt -match 'hostname:\s*(\S+)') { $url = "https://$($Matches[1])" }
        }
    }

    if ($url) { $url | Set-Content -LiteralPath $urlFile -Encoding ASCII }

    # Mantém o sistema acordado enquanto o túnel viver (thread principal).
    [void][Win32.Power]::SetThreadExecutionState($ES_AWAKE)

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 20
        [void][Win32.Power]::SetThreadExecutionState($ES_AWAKE)
    }

    [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS)
    "TUNEL_TERMINADO $(Get-Date -Format s) exit=$($proc.ExitCode)" | Add-Content -LiteralPath $errFile
    exit 0
}

# ---------------------------------------------------------------------------
# Arranque (primeiro plano, devolve o link)
# ---------------------------------------------------------------------------
Write-Step 'Verificar a stack local'
try {
    $r = Invoke-WebRequest -Uri "$Origin/api/health" -UseBasicParsing -TimeoutSec 10
    Write-Ok "respondeu $($r.StatusCode) em $Origin"
}
catch {
    Write-Bad "$Origin/api/health não respondeu."
    Write-Warn2 'Arranca a stack com: cd c:\LLMFinance\finance-llm ; docker compose up -d'
    throw 'Sem origem não vale a pena publicar.'
}

if ($SetPowerTimeouts) {
    Write-Step 'Desativar timeouts de suspensão/hibernação no plano ativo'
    foreach ($par in @('standby-timeout-ac', 'hibernate-timeout-ac', 'standby-timeout-dc', 'hibernate-timeout-dc')) {
        powercfg /change $par 0 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok "$par = nunca" }
        else { Write-Warn2 "$par não alterado (precisa de Administrador)" }
    }
}

Write-Step 'Arrancar o túnel em segundo plano'
$running = Get-RunningProcesses
if ($running.Worker) {
    Write-Warn2 "Já estava a correr (worker PID $($running.Worker.Id)). Parar primeiro: .\public-link.ps1 -Stop"
    exit 1
}

$argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-Worker', '-Origin', $Origin)
if ($ConfigPath) {
    if (-not (Test-Path $ConfigPath)) { throw "Config não encontrada: $ConfigPath" }
    $argList += @('-ConfigPath', (Resolve-Path $ConfigPath).Path)
}
Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -WindowStyle Hidden | Out-Null

$deadline = (Get-Date).AddSeconds(100)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $urlFile) { break }
    Start-Sleep -Milliseconds 800
}

if (-not (Test-Path $urlFile)) {
    Write-Bad 'Não consegui obter o link. Vê public-link.err.log.'
    exit 1
}

$url = (Get-Content -LiteralPath $urlFile -Raw).Trim()
Write-Ok 'link ativo'
Write-Host ''
Write-Host '  ================================================' -ForegroundColor Green
Write-Host "   $url" -ForegroundColor Green
Write-Host '  ================================================' -ForegroundColor Green
$resumo = @"

Estado:
  processo do túnel   : destacado (continua depois de fechares este terminal)
  PC a dormir/hibernar: BLOQUEADO enquanto o túnel viver
  logs                : public-link.log / public-link.err.log
  origem publicada    : $Origin

Avisos:
  * Um quick tunnel não tem Cloudflare Access: quem tiver o link chega à
    plataforma (a autenticação da app continua a ser pedida). Trata o link como
    segredo e não o abras a terceiros.
  * O link muda a cada arranque. Para link fixo com Access, corre primeiro
    .\01-setup-tunnels.ps1 e depois: .\public-link.ps1 -ConfigPath .\origin\config.yml
  * As páginas iframe (n8n, Hermes, SearXNG) usam portas 8891/8892/8888 e não
    passam pelo túnel.

Para parar:  .\public-link.ps1 -Stop
"@
Write-Host $resumo -ForegroundColor Gray
