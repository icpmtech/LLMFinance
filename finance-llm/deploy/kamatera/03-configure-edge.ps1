#requires -Version 5.1
<#
.SYNOPSIS
    Aplica a configuracao do edge na VM Kamatera (dominio proprio sabemos.studio).

.DESCRIPTION
    Envia o `05-edge-up.sh`, o `edge/Caddyfile` e o `edge/compose.yml` para a VM
    (por ssh + base64: nesta rede o `scp` fica preso) e corre o `05`, que arranca
    o Caddy. No fim mostra o endereco publico fixo https://sabemos.studio.

    O upstream do Caddy e `127.0.0.1:8080` da VM, onde o PC publica a stack pelo
    tunel SSH reverso (`07-origin-tunnel.ps1`). Nao ha Cloudflare nem hostname
    aleatorio para propagar - por isso este script ja nao le `origin-url.txt`.

    Todas as ligacoes SSH sao repetidas: a rede para esta VM perde ligacoes de
    forma intermitente (o SYN fica sem resposta), mas a VM esta saudavel.

.EXAMPLE
    .\03-configure-edge.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [int]$Attempts = 40
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-VmSsh {
    param([Parameter(Mandatory = $true)][string]$Command)
    for ($i = 1; $i -le $Attempts; $i++) {
        # O ssh escreve os erros de ligacao em stderr; com ErrorActionPreference a
        # Stop isso vira erro terminante em vez de dar nova tentativa.
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $out = & ssh -i $SshKey -o BatchMode=yes -o ConnectTimeout=8 `
            -o ServerAliveInterval=5 -o ServerAliveCountMax=2 `
            -o LogLevel=ERROR "$SshUser@$SshHost" $Command 2>&1
        $rc = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($rc -eq 0) { return ($out -join "`n") }
        Write-Host ("  tentativa {0}/{1} falhou, a repetir..." -f $i, $Attempts) -ForegroundColor DarkGray
        Start-Sleep -Seconds 2
    }
    throw "ssh falhou apos $Attempts tentativas"
}

Write-Host "origem: tunel SSH reverso para 127.0.0.1:8080 na VM"

# Enviar os ficheiros do edge (base64, sem scp).
$setupLocal = Join-Path $here '05-edge-up.sh'
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($setupLocal))
$push = "printf %s '$b64' | base64 -d > /opt/iqos/05-edge-up.sh; sed -i 's/\r$//' /opt/iqos/05-edge-up.sh; wc -c /opt/iqos/05-edge-up.sh"
Write-Host 'a enviar 05-edge-up.sh por ssh...'
Write-Host (Invoke-VmSsh -Command $push)

# O Caddyfile ja nao tem placeholders: e copiado tal e qual.
$caddyLocal = Join-Path $here 'edge\Caddyfile'
$caddyB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($caddyLocal))
$pushCaddy = "mkdir -p /opt/iqos/edge; printf %s '$caddyB64' | base64 -d > /opt/iqos/edge/Caddyfile; sed -i 's/\r$//' /opt/iqos/edge/Caddyfile; wc -c /opt/iqos/edge/Caddyfile"
Write-Host 'a enviar Caddyfile por ssh...'
Write-Host (Invoke-VmSsh -Command $pushCaddy)

# 3) Enviar o compose do edge.
$composeLocal = Join-Path $here 'edge\compose.yml'
$composeB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($composeLocal))
$pushCompose = "printf %s '$composeB64' | base64 -d > /opt/iqos/edge/compose.yml; sed -i 's/\r$//' /opt/iqos/edge/compose.yml; wc -c /opt/iqos/edge/compose.yml"
Write-Host 'a enviar compose.yml por ssh...'
Write-Host (Invoke-VmSsh -Command $pushCompose)

# 4) Arrancar o edge.
Write-Host 'a arrancar o edge...'
Invoke-VmSsh -Command "bash /opt/iqos/05-edge-up.sh 2>&1 | tail -30" | Write-Host

'https://sabemos.studio' | Set-Content -Path (Join-Path $here 'public-url.txt') -Encoding ascii
Write-Host ''
Write-Host "==> Edge IQ OS publicado em: https://sabemos.studio" -ForegroundColor Yellow
