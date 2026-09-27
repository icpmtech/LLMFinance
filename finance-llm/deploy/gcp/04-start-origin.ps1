#requires -Version 5.1
<#
.SYNOPSIS
    Arranca o túnel de origem: publica a stack local ($LocalOrigin) no
    hostname de origem, para o edge na Google Cloud a poder alcançar.

.DESCRIPTION
    Corre no PC, com a stack local já a correr. Por omissão fica em primeiro
    plano (Ctrl+C desliga); com -AsService imprime as instruções para o deixar
    permanente como serviço do Windows.

.EXAMPLE
    .\04-start-origin.ps1
.EXAMPLE
    .\04-start-origin.ps1 -AsService
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'origin\config.yml'),
    [string]$LocalOrigin = 'http://127.0.0.1:4180',
    [switch]$AsService
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) { throw 'cloudflared não está no PATH (winget install Cloudflare.cloudflared).' }

Write-Step 'Verificar config do túnel'
if (-not (Test-Path $ConfigPath)) {
    throw "Config não encontrada: $ConfigPath. Corre primeiro .\01-setup-tunnels.ps1"
}
$cfg = Get-Content -LiteralPath $ConfigPath -Raw
$tunnelId = ([regex]'tunnel:\s*([0-9a-f-]{36})').Match($cfg).Groups[1].Value
$originHostname = ([regex]'hostname:\s*(\S+)').Match($cfg).Groups[1].Value
if (-not $tunnelId) { throw "Não encontrei o UUID do túnel em $ConfigPath" }
Write-Ok "túnel $tunnelId -> $originHostname"

Write-Step 'Verificar a stack local'
try {
    $r = Invoke-WebRequest -Uri "$LocalOrigin/api/health" -UseBasicParsing -TimeoutSec 10
    Write-Ok "stack local respondeu $($r.StatusCode) em $LocalOrigin"
}
catch {
    Write-Warn2 "A stack local não respondeu em $LocalOrigin/api/health"
    Write-Warn2 'Arranca-a com: docker compose up -d  (na raiz do finance-llm)'
    Write-Warn2 'O túnel vai arrancar à mesma, mas o edge mostrará a página de manutenção.'
}

if ($AsService) {
    $servico = @"

================================================================================
PÔR O TÚNEL DE ORIGEM COMO SERVIÇO (PowerShell como Administrador)
================================================================================
Um serviço do Windows corre como SYSTEM, cujo perfil é outro — a config e as
credenciais têm de ser copiadas para lá:

  `$cfdir = 'C:\Windows\System32\config\systemprofile\.cloudflared'
  New-Item -ItemType Directory -Force -Path `$cfdir | Out-Null
  Copy-Item '$ConfigPath' `$cfdir\config.yml -Force
  Copy-Item (Join-Path `$env:USERPROFILE '.cloudflared\$tunnelId.json') `$cfdir -Force
  cloudflared service install
  Start-Service cloudflared

Alternativa sem administrador (arranca no teu login) — Agendador de Tarefas:
  Trigger: Ao iniciar sessão | Ação: cloudflared tunnel --config "$ConfigPath" run

O serviço só existe enquanto o PC estiver ligado. Isso é inerente a este
desenho: a stack e os dados (~36 GB) continuam locais.
"@
    Write-Host $servico -ForegroundColor Gray
    return
}

Write-Step 'Arrancar o túnel de origem (Ctrl+C para parar)'
Write-Host "    O edge em https://... vai passar a chegar à stack local." -ForegroundColor Gray
& $cf.Source tunnel --config $ConfigPath run
