#requires -Version 5.1
<#
.SYNOPSIS
    Migra os indices do Elasticsearch local para o da VM do edge.

.DESCRIPTION
    Envia `es/migrar.sh` para a VM e corre-o la dentro. O trabalho pesado e o
    `_reindex` do proprio Elasticsearch (com `source.remote` apontado ao ES do
    PC pelo tunel em 127.0.0.1:9201) -- este script so o dispara e mostra o
    resultado.

    Nao mexe no ES local: so le. E nao toca em mais nada da VM.

    Como o ficheiro vai por stdin do `ssh`, nao ha limite de tamanho nem
    problemas de aspas; os CR sao removidos do lado de ca.

.EXAMPLE
    # Ver o que seria migrado, sem escrever nada
    .\12-es-migrar.ps1 -MaxGB 3 -Dry

.EXAMPLE
    # Migrar de facto (comeca pelos leves)
    .\12-es-migrar.ps1 -MaxGB 3

.EXAMPLE
    # Refazer indices que ja existam
    .\12-es-migrar.ps1 -MaxGB 3 -Force
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$RemoteDir = '/opt/iqos/es',
    [double]$MaxGB = 3,
    [switch]$Dry,
    [switch]$Force,
    # So os indices cuja contagem diverge da origem. E o modo para realinhar o
    # espelho depois de o sistema ter escrito coisas novas.
    [switch]$Sync
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptLocal = Join-Path $here 'es\migrar.sh'
if (-not (Test-Path $scriptLocal)) { throw "nao encontro $scriptLocal" }

function Invoke-VmRaw {
    # `-i` mantem o stdin aberto, para o `Send-VmFile` poder escrever.
    param([Parameter(Mandatory)][string]$RemoteCommand, [switch]$WithStdin)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($WithStdin) {
            $out = docker exec -i $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
                -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand
        } else {
            $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
                -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand
        }
    } finally {
        $ErrorActionPreference = $prev
    }
    return $out
}

Write-Host ''
Write-Host '=== A enviar o migrar.sh ===' -ForegroundColor Cyan
$conteudo = (Get-Content -Raw $scriptLocal) -replace "`r`n", "`n"
# Via stdin: sem limite de tamanho e sem lutar com aspas dentro do comando remoto.
$conteudo | docker exec -i $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
    -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" `
    "mkdir -p $RemoteDir && cat > $RemoteDir/migrar.sh"
if ($LASTEXITCODE -ne 0) { throw 'falhou o envio do migrar.sh' }
# O PowerShell injecta CR ao escrever numa pipeline nativa, mesmo depois do
# `-replace` acima (o `bash` rebenta com "$'\r': command not found"). Limpar
# outra vez do lado de la e a unica forma fiavel.
& docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
    -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" `
    "sed -i 's/\r`$//' $RemoteDir/migrar.sh"
$tamanho = (Invoke-VmRaw "wc -c < $RemoteDir/migrar.sh").Trim()
$crs = (Invoke-VmRaw "grep -c `$'\r' $RemoteDir/migrar.sh || true").Trim()
Write-Host "  $RemoteDir/migrar.sh ($tamanho bytes, linhas com CR: $crs)"
if ($crs -ne '0') { throw "o ficheiro ainda tem $crs linhas com CR." }

$env_remoto = "SOURCE=http://127.0.0.1:9201 DEST=http://127.0.0.1:9200 MAX_MB=$([int]($MaxGB * 1024)) DRY=$(if ($Dry) { 1 } else { 0 }) FORCE=$(if ($Force) { 1 } else { 0 }) SYNC=$(if ($Sync) { 1 } else { 0 })"

Write-Host ''
if ($Dry) {
    Write-Host '=== Simulacao (nada e escrito) ===' -ForegroundColor Cyan
} else {
    Write-Host '=== A migrar ===' -ForegroundColor Cyan
}
Write-Host "  MAX_GB=$MaxGB  DRY=$(if ($Dry) { 1 } else { 0 })  FORCE=$(if ($Force) { 1 } else { 0 })  SYNC=$(if ($Sync) { 1 } else { 0 })"
Write-Host ''

# `bash` e obrigatorio: o /bin/sh do Ubuntu e dash e nao tem `pipefail` nem
# herestrings, que o migrar.sh usa.
& docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
    -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" `
    "cd $RemoteDir && $env_remoto bash migrar.sh"
$codigo = $LASTEXITCODE

Write-Host ''
if ($codigo -eq 0) {
    Write-Host 'Concluido sem divergencias.' -ForegroundColor Green
} else {
    Write-Host "Terminou com codigo $codigo -- ver as linhas DIVERGE/FALHOU acima." -ForegroundColor Yellow
}
