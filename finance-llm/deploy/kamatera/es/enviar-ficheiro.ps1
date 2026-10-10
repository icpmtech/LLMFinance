# Envia um ficheiro de texto local para a VM, por base64 sobre ssh.
#
# Porque e que isto existe
# ------------------------
# Nao ha `scp` utilizavel nesta rede (fica preso, sem erro nem timeout), e as
# aspas nao sobrevivem a passagem PowerShell -> ssh: passar um script Python como
# argumento de `python -c "..."` chega truncado a VM. Base64 evita as aspas todas.
#
# O `|` tambem e comido nesse caminho, por isso a descodificacao le de um
# **ficheiro** (`base64 -d ficheiro`) em vez de ler do stdin.
#
# O envio e feito em pedacos: uma linha unica com centenas de KB de base64 nao
# sobrevive ao `echo`.
#
#     .\enviar-ficheiro.ps1 -Local .\_diag.py -Remoto /opt/iqos/diag.py
#     .\enviar-ficheiro.ps1 -Local .\_diag.py -Remoto /opt/iqos/diag.py -ExecutarEm iqos-backend

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $Local,
    [Parameter(Mandatory)][string] $Remoto,
    [string] $TunnelContainer = 'iqos-origin-tunnel',
    [string] $SshUser = 'root',
    [string] $SshHost = '45.147.251.188',
    # Se dado, corre o ficheiro dentro deste contentor: `python <Remoto>`.
    [string] $ExecutarEm
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Local)) { throw "nao encontro $Local" }

function Invoke-Vm {
    param([Parameter(Mandatory)][string] $Comando)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $Comando 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

$tamLocal = (Get-Item $Local).Length
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($Local))

Write-Host ("a enviar {0} ({1:N0} bytes, {2:N0} em base64)" -f `
    (Split-Path $Local -Leaf), $tamLocal, $b64.Length)

# Ficheiro temporario limpo primeiro, senao `>>` acumulava com uma tentativa anterior.
Invoke-Vm 'rm -f /tmp/iqos-envio.b64' | Out-Null

$pedaco = 3000
$primeiro = $true
$enviados = 0
for ($i = 0; $i -lt $b64.Length; $i += $pedaco) {
    $len = [Math]::Min($pedaco, $b64.Length - $i)
    $parte = $b64.Substring($i, $len)
    # O primeiro pedaco cria o ficheiro, os seguintes acrescentam.
    $redir = if ($primeiro) { '>' } else { '>>' }
    $r = Invoke-Vm "echo '$parte' $redir /tmp/iqos-envio.b64"
    if ($r.ExitCode -ne 0) { throw "falhou o pedaco $enviados : $($r.Output)" }
    $primeiro = $false
    $enviados++
}

$fim = Invoke-Vm "base64 -d /tmp/iqos-envio.b64 > $Remoto; rm -f /tmp/iqos-envio.b64; wc -c < $Remoto"
$tamVm = 0
if ($fim.Output -match '(\d+)') { $tamVm = [int64]$Matches[1] }

if ($tamVm -ne $tamLocal) {
    throw "$Remoto chegou com $tamVm bytes em vez de $tamLocal"
}
Write-Host ("  ok: {0} bytes em {1} (em {2} pedacos)" -f $tamVm, $Remoto, $enviados) -ForegroundColor Green

if ($ExecutarEm) {
    Write-Host ("  a correr dentro de {0}..." -f $ExecutarEm) -ForegroundColor DarkGray
    $exec = Invoke-Vm "docker exec $ExecutarEm python $Remoto"
    Write-Host $exec.Output
    exit $exec.ExitCode
}
