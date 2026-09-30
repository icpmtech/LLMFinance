#Requires -Version 5.1
<#
    Cria um quick tunnel Cloudflare para http://127.0.0.1:8002
    e impede hibernação/standby enquanto o túnel corre.
    Ctrl+C nesta janela para parar.
#>
$ErrorActionPreference = "Stop"

$base = "C:\LLMFinance"
$logOut = Join-Path $base "_tunnel_8002.log"
$logErr = Join-Path $base "_tunnel_8002.err.log"
$pidFile = Join-Path $base "_tunnel_8002.pid"
$urlFile = Join-Path $base "_tunnel_8002_url.txt"

# 1. Manter o sistema acordado enquanto o túnel está activo
$keepAlive = Start-Job -Name "KeepAlive8002" -ScriptBlock {
    Add-Type -MemberDefinition '[DllImport("kernel32.dll")]public static extern uint SetThreadExecutionState(uint es);' -Name System -Namespace Win32
    while ($true) {
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        [void][Win32.System]::SetThreadExecutionState(0x80000003)
        Start-Sleep -Seconds 30
    }
}

# 2. Arrancar cloudflared (quick tunnel, sem conta, sem autoupdate)
$proc = Start-Process -FilePath "cloudflared" `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:8002", "--no-autoupdate" `
    -RedirectStandardOutput $logOut `
    -RedirectStandardError $logErr `
    -NoNewWindow -PassThru

$proc.Id | Out-File $pidFile -Encoding utf8

# 3. Esperar que o URL apareça nos logs
$url = $null
$timeout = 60
$sw = [System.Diagnostics.Stopwatch]::StartNew()
while ((-not $url) -and ($sw.Elapsed.TotalSeconds -lt $timeout)) {
    Start-Sleep -Seconds 2
    $lines = @()
    if (Test-Path $logOut) { $lines += Get-Content $logOut -ErrorAction SilentlyContinue }
    if (Test-Path $logErr) { $lines += Get-Content $logErr -ErrorAction SilentlyContinue }
    $match = $lines | Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
    if ($match) {
        $url = $match.Matches[0].Value
    }
}

if ($url) {
    Write-Host "`nTUNNEL URL: $url" -ForegroundColor Green
    $url | Out-File $urlFile -Encoding utf8
} else {
    Write-Host "`nNao foi possivel obter o URL do tunnel dentro de ${timeout}s." -ForegroundColor Red
    Write-Host "Ver logs: $logErr"
}

Write-Host "`nTunel activo em http://127.0.0.1:8002. Prima Ctrl+C aqui para parar." -ForegroundColor Cyan

# 4. Aguardar ate ser interrompido
$proc.WaitForExit()
