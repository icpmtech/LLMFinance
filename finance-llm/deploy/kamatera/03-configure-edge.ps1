#requires -Version 5.1
<#
.SYNOPSIS
    Aplica o hostname da origem no edge da VM Kamatera e mostra o endereco publico.

.DESCRIPTION
    Le `origin-url.txt` (criado por 02-publish-origin.ps1), envia o
    `05-edge-up.sh` para a VM (por ssh + base64: nesta rede o `scp` fica preso) e
    corre-o com o hostname. No fim le o endereco publico do tunel da VM.

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
$urlFile = Join-Path $here 'origin-url.txt'

if (-not (Test-Path $urlFile)) { throw "Falta $urlFile. Corre primeiro 02-publish-origin.ps1." }
$originHost = (Get-Content $urlFile -Raw).Trim()
if ($originHost -notmatch '\.trycloudflare\.com$') { throw "Hostname de origem invalido: '$originHost'" }

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

Write-Host "origem: $originHost"

# 1) Enviar o script de arranque do edge (base64, sem scp).
$setupLocal = Join-Path $here '05-edge-up.sh'
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($setupLocal))
$push = "printf %s '$b64' | base64 -d > /opt/iqos/05-edge-up.sh; sed -i 's/\r$//' /opt/iqos/05-edge-up.sh; wc -c /opt/iqos/05-edge-up.sh"
Write-Host 'a enviar 05-edge-up.sh por ssh...'
Write-Host (Invoke-VmSsh -Command $push)

# 2) Aplicar o hostname e arrancar o edge.
Write-Host 'a arrancar o edge...'
Invoke-VmSsh -Command "bash /opt/iqos/05-edge-up.sh $originHost 2>&1 | tail -25" | Write-Host

# 3) Ler o endereco publico do tunel da VM.
$logs = Invoke-VmSsh -Command "docker logs iqos-tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | head -1"
$m = [regex]::Match($logs, 'https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com')
if (-not $m.Success) { throw "Nao encontrei o endereco publico. Ver: ssh ... 'docker logs iqos-tunnel'" }

$m.Value | Set-Content -Path (Join-Path $here 'public-url.txt') -Encoding ascii
Write-Host ''
Write-Host "==> Edge IQ OS publicado em: $($m.Value)" -ForegroundColor Yellow
