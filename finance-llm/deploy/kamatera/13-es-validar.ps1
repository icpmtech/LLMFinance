#requires -Version 5.1
<#
.SYNOPSIS
    Valida o espelho do Elasticsearch na VM contra o ES local.

.DESCRIPTION
    Envia `es/validar.sh` para a VM e corre-o la. So leitura: nao escreve em
    nenhum dos dois clusters, nao toca em contentores, nao altera nada.

    Compara, para cada indice que exista no destino, a contagem de documentos e
    o mapeamento (normalizado). No fim lista o que exista so num dos lados.

.EXAMPLE
    .\13-es-validar.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$RemoteDir = '/opt/iqos/es'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptLocal = Join-Path $here 'es\validar.sh'
if (-not (Test-Path $scriptLocal)) { throw "nao encontro $scriptLocal" }

function Invoke-VmRaw {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand
    } finally {
        $ErrorActionPreference = $prev
    }
    return $out
}

Write-Host ''
Write-Host '=== A enviar o validar.sh ===' -ForegroundColor Cyan
$conteudo = (Get-Content -Raw $scriptLocal) -replace "`r`n", "`n"
$conteudo | docker exec -i $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
    -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" `
    "mkdir -p $RemoteDir && cat > $RemoteDir/validar.sh"
if ($LASTEXITCODE -ne 0) { throw 'falhou o envio do validar.sh' }
# O PowerShell injecta CR ao escrever em pipeline nativa; o bash rebenta com isso.
& docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
    -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" `
    "sed -i 's/\r`$//' $RemoteDir/validar.sh"
$tamanho = (Invoke-VmRaw "wc -c < $RemoteDir/validar.sh").Trim()
Write-Host "  $RemoteDir/validar.sh ($tamanho bytes)"

Write-Host ''
Write-Host '=== A validar (leitura apenas) ===' -ForegroundColor Cyan
Write-Host ''

& docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
    -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" `
    "cd $RemoteDir && SOURCE=http://127.0.0.1:9201 DEST=http://127.0.0.1:9200 bash validar.sh"
$codigo = $LASTEXITCODE

Write-Host ''
if ($codigo -eq 0) {
    Write-Host 'Espelho validado sem divergencias.' -ForegroundColor Green
} else {
    Write-Host "Encontrei divergencias (codigo $codigo) -- ver as linhas <-- VER acima." -ForegroundColor Yellow
}
