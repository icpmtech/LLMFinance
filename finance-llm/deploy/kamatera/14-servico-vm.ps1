#requires -Version 5.1
<#
.SYNOPSIS
    Migra um servico do IQ OS para a VM do edge, um de cada vez.

.DESCRIPTION
    Cada servico vive em `servicos/<nome>/compose.yml` e arranca como projeto
    Docker proprio em `/opt/iqos/servicos/<nome>`. Consequencias:

      - `docker compose up` ali dentro so mexe nos contentores daquele projeto;
      - o Caddy, a landing, o Elasticsearch e o tunel nunca sao tocados;
      - o stack do PC nao e tocado (nada aqui lhe toca);
      - a porta de cada servico fica presa a 127.0.0.1 na VM.

    Os ficheiros de configuracao que cada servico precisa estao declarados em
    `$SERVICOS`, para nao duplicar no repositorio o que ja existe (`docker/<x>`).

.EXAMPLE
    .\14-servico-vm.ps1 -Listar
    .\14-servico-vm.ps1 -Nome searxng
    .\14-servico-vm.ps1 -Nome searxng -Logs
    .\14-servico-vm.ps1 -Nome searxng -Parar
#>
[CmdletBinding(DefaultParameterSetName = 'Aplicar')]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$BaseDir = '/opt/iqos/servicos',

    [Parameter(ParameterSetName = 'Aplicar')]
    [string]$Nome,

    [Parameter(ParameterSetName = 'Listar')]
    [switch]$Listar,

    [Parameter(ParameterSetName = 'Aplicar')]
    [switch]$Logs,

    [Parameter(ParameterSetName = 'Aplicar')]
    [switch]$Parar
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$servicosDir = Join-Path $here 'servicos'
$raiz = Join-Path $here '..\..'   # finance-llm/

# Cada servico: porta local na VM, ficheiros de configuracao a enviar, e o
# caminho a sondar para validar. Acrescentar aqui ao migrar o proximo.
$SERVICOS = @{
    'searxng' = @{
        Porta = 8888
        Sonda = '/'
        Extra = @(
            @{ Local = (Join-Path $raiz 'docker\searxng\settings.yml')
               RemoteDir = "$BaseDir/searxng/etc"
               RemoteFile = 'settings.yml' }
        )
    }
    'n8n' = @{
        Porta = 5678
        Sonda = '/healthz'
        Extra = @(
            @{ Local = (Join-Path $raiz 'docker\n8n\LEIA-ME.md')
               RemoteDir = "$BaseDir/n8n/files"
               RemoteFile = 'LEIA-ME.md' }
        )
    }
    # A imagem deste e construida localmente: transferir primeiro com
    # `15-imagem-vm.ps1 -Imagem iq-os-frontend:latest`.
    'frontend' = @{
        Porta = 4180
        Sonda = '/'
        Extra = @()
    }
}

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

function Show-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $r = Invoke-Vm $RemoteCommand
    if ($r.Output) { $r.Output -split "`n" | ForEach-Object { Write-Host "  $_" } }
    return $r
}

function Send-VmFile {
    param([Parameter(Mandatory)][string]$Local, [Parameter(Mandatory)][string]$RemoteDir,
          [Parameter(Mandatory)][string]$RemoteFile)
    if (-not (Test-Path $Local)) { throw "nao encontro $Local" }
    # Por stdin: sem limite de tamanho e sem lutar com aspas dentro do comando.
    (Get-Content -Raw $Local) -replace "`r`n", "`n" | docker exec -i $TunnelContainer `
        ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 -o LogLevel=ERROR `
        "$SshUser@$SshHost" "mkdir -p $RemoteDir && cat > $RemoteDir/$RemoteFile"
    if ($LASTEXITCODE -ne 0) { throw "falhou o envio de $RemoteFile" }
    # O PowerShell injecta CR ao escrever em pipeline nativa.
    Invoke-Vm "sed -i 's/\r`$//' $RemoteDir/$RemoteFile" | Out-Null
    $tam = (Invoke-Vm "wc -c < $RemoteDir/$RemoteFile").Output.Trim()
    Write-Host "  $RemoteDir/$RemoteFile ($tam bytes)"
}

if ($Listar) {
    Write-Host ''
    Write-Host 'Servicos disponiveis em servicos/:' -ForegroundColor Cyan
    foreach ($k in $SERVICOS.Keys | Sort-Object) {
        $porta = $SERVICOS[$k].Porta
        Write-Host ("  {0,-12} porta 127.0.0.1:{1}" -f $k, $porta)
    }
    Write-Host ''
    return
}

if (-not $Nome) { throw 'indica -Nome <servico> (ou -Listar para ver as opcoes).' }

$cfg = $SERVICOS[$Nome]
if (-not $cfg) { throw "servico '$Nome' nao esta em `$SERVICOS`. Usa -Listar." }

$composeLocal = Join-Path $servicosDir "$Nome\compose.yml"
if (-not (Test-Path $composeLocal)) { throw "nao encontro $composeLocal" }

$remoteDir = "$BaseDir/$Nome"

if ($Logs) {
    & docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
        "$SshUser@$SshHost" "cd $remoteDir && docker compose logs -f --tail 60"
    return
}

if ($Parar) {
    Write-Host "a parar $Nome..." -ForegroundColor Cyan
    Show-Vm "cd $remoteDir && docker compose down" | Out-Null
    return
}

Write-Host ''
Write-Host "=== A migrar '$Nome' para a VM ===" -ForegroundColor Cyan
Write-Host "  destino: $remoteDir"
Write-Host ''
Write-Host '  Antes (VM):'
Show-Vm 'free -m | sed -n 2p; df -h / | tail -1' | Out-Null

Write-Host ''
Write-Host '=== 1. A enviar ficheiros ===' -ForegroundColor Cyan
Send-VmFile -Local $composeLocal -RemoteDir $remoteDir -RemoteFile 'compose.yml'
foreach ($f in $cfg.Extra) { Send-VmFile -Local $f.Local -RemoteDir $f.RemoteDir -RemoteFile $f.RemoteFile }

Write-Host ''
Write-Host '=== 2. A arrancar ===' -ForegroundColor Cyan
Write-Host '  (projeto proprio: o edge, o ES e o tunel ficam intocados)'
Show-Vm "cd $remoteDir && docker compose up -d 2>&1" | Out-Null

Write-Host ''
Write-Host '=== 3. A aguardar resposta ===' -ForegroundColor Cyan
# Valida por HTTP e nao pelo healthcheck: nem todos os servicos do stack tem um
# (`services/*/compose.yml` pode nao definir `healthcheck`), e um healthcheck mal
# escrito faria isto esperar para sempre por um servico que esta bom.
$vivo = $false
for ($i = 1; $i -le 24; $i++) {
    $estado = (Invoke-Vm "cd $remoteDir && docker compose ps --format '{{.Status}}'").Output
    $codigo = (Invoke-Vm "curl -s -o /dev/null -m 5 -w %{http_code} http://127.0.0.1:$($cfg.Porta)$($cfg.Sonda)").Output.Trim()
    if ($codigo -match '^[234]') {
        Write-Host "  respondeu HTTP $codigo na tentativa $i" -ForegroundColor Green
        $vivo = $true
        break
    }
    Write-Host "  tentativa $i : HTTP $codigo / $estado"
    Start-Sleep -Seconds 10
}
if (-not $vivo) {
    Write-Host '  NAO respondeu. Log:' -ForegroundColor Red
    Show-Vm "cd $remoteDir && docker compose logs --tail 30" | Out-Null
    throw "o servico '$Nome' nao arrancou."
}

Write-Host ''
Write-Host '=== 4. Validacao ===' -ForegroundColor Cyan
Show-Vm 'docker container ls --format table --filter name=iqos-' | Out-Null
Write-Host ''
Write-Host "  sonda   http://127.0.0.1:$($cfg.Porta)$($cfg.Sonda)"
Write-Host "    HTTP $codigo  (2xx/3xx/4xx provam que o servico esta vivo)"

Write-Host ''
Write-Host '  Depois (VM):'
Show-Vm 'free -m | sed -n 2p; df -h / | tail -1' | Out-Null
Write-Host ''
Write-Host "  O servico escuta so em 127.0.0.1:$($cfg.Porta) -- nao esta exposto." -ForegroundColor DarkGray
Write-Host ''
