#requires -Version 5.1
<#
.SYNOPSIS
    Prepara e verifica o DNS do servidor de email da VM (Docker Mailserver).

.DESCRIPTION
    Um servidor de correio so vale o que valer o DNS que o acompanha: sem SPF,
    DKIM, DMARC e PTR o correio sai -- e vai para o spam, ou e recusado. Este
    script trata da parte que se pode automatizar e diz o que falta:

      1. gera a chave DKIM no contentor (se ainda nao existir) e recria-o, porque
         o DMS so assina depois de reiniciar;
      2. escreve o registo DKIM **numa linha**, que e como se cola num painel de
         DNS: o ficheiro do DMS e um bloco de zona, com aspas e parenteses;
      3. le o DNS publico (via DNS-over-HTTPS, logo ve o que o mundo ve) e compara
         com o que devia estar publicado: A, MX, SPF, DKIM, DMARC e PTR.

    O PTR (DNS inverso) nao se configura no DNS do dominio: e do lado da Kamatera.
    Sem ele, o HELO (`mail.sabemos.studio`) e o endereco de origem nao batem certo
    e os grandes fornecedores classificam o correio como spam. O script mostra se
    ja esta posto, mas nao o pode pôr.

.EXAMPLE
    .\23-email-dns.ps1
    .\23-email-dns.ps1 -Dominio sabemos.studio -Ip 45.147.251.188
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$Contentor = 'iqos-mailserver',
    # O dominio do correio (sem subdominio). E a zona onde entram o MX e o SPF.
    [string]$Dominio = 'sabemos.studio',
    # O FQDN do servidor de correio: e o valor do MX, do registo A e do HELO.
    [string]$Servidor = 'mail.sabemos.studio',
    [string]$Seletor = 'mail',
    # O IP publico da VM. Tem de ser **estatico**: e a ele que se cola o PTR.
    [string]$Ip = '45.147.251.188',
    [string]$Postmaster = 'postmaster@sabemos.studio'
)

$ErrorActionPreference = 'Stop'

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

# Le uma resposta do DNS-over-HTTPS do Google. Vai pela Internet e nao pelo
# resolver do PC de proposito: e para ver o que o **mundo** ve, com os mesmos
# caches que um servidor de correio externo vai consultar.
function Resolve-Dns {
    param([Parameter(Mandatory)][string]$Nome, [Parameter(Mandatory)][string]$Tipo)
    try {
        $r = Invoke-RestMethod -Uri "https://dns.google/resolve?name=$Nome&type=$Tipo" -TimeoutSec 15
    } catch {
        Write-Host "    (falhou a consulta DNS de $Nome $Tipo : $($_.Exception.Message))" -ForegroundColor DarkGray
        return @()
    }
    if (-not $r.Answer) { return @() }
    # O valor de um TXT vem entre aspas na resposta.
    return @($r.Answer | ForEach-Object { "$($_.data)".Trim('"') })
}

$problemas = 0

function Check {
    param(
        [Parameter(Mandatory)][string]$O_Que,
        [Parameter(Mandatory)][bool]$Ok,
        [Parameter(Mandatory)][string]$Detalhe,
        [string]$Sugestao = ''
    )
    if ($Ok) {
        Write-Host ("  {0,-22} {1}" -f $O_Que, $Detalhe) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-22} {1}" -f $O_Que, $Detalhe) -ForegroundColor Red
        if ($Sugestao) { Write-Host ("  {0,-22} -> {1}" -f '', $Sugestao) -ForegroundColor Yellow }
        $script:problemas++
    }
}

# ---------------------------------------------------------------------------
# 1. Chave DKIM
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '=== 1. Chave DKIM ===' -ForegroundColor Cyan
$caminhoChave = "/tmp/docker-mailserver/opendkim/keys/$Dominio/$Seletor.txt"
$valorDkim = ''
$temChave = $false

if (-not (docker ps --filter "name=$TunnelContainer" --format '{{.Names}}')) {
    Write-Host "  o container $TunnelContainer nao esta a correr (ver 07-origin-tunnel.ps1)." -ForegroundColor Yellow
    Write-Host '  Sem VM nao ha chave para ler: sigo para a verificacao do DNS.' -ForegroundColor Yellow
} else {
    $aCorrer = (Invoke-Vm "docker ps --filter name=^$Contentor`$ --format '{{.Names}}'").Output.Trim()
    if (-not $aCorrer) {
        Write-Host "  o $Contentor nao esta a correr na VM: corre primeiro" -ForegroundColor Yellow
        Write-Host '    .\14-servico-vm.ps1 -Nome mailserver' -ForegroundColor Yellow
    } else {
        $existe = (Invoke-Vm "test -f $caminhoChave && echo sim").Output.Trim()
        if ($existe -ne 'sim') {
            Write-Host "  sem chave em $caminhoChave -- a gerar (setup config dkim)"
            $gerar = Invoke-Vm "docker exec $Contentor setup config dkim 2>&1 | tail -3"
            $gerar.Output -split "`n" | ForEach-Object { Write-Host "  $_" }
            # O DMS so passa a assinar depois de reiniciar: a chave e lida no
            # arranque e o OpenDKIM nao a vai buscar sozinho.
            Write-Host '  a recriar o contentor (so se assina depois de reiniciar)'
            Invoke-Vm "cd /opt/iqos/servicos/mailserver && docker compose up -d --force-recreate 2>&1 | tail -2" |
                Select-Object -ExpandProperty Output | ForEach-Object { Write-Host "  $_" }
        }

        # O ficheiro do DMS e um bloco de zona:
        #
        #     mail._domainkey	IN	TXT	( "v=DKIM1; h=sha256; k=rsa; "
        #     	  "p=MIIB...primeira metade"
        #     	  "...segunda metade" )  ; ----- DKIM key mail for sabemos.studio
        #
        # Num painel de DNS cola-se o **valor**, numa linha, sem aspas nem
        # parenteses. Vai-se buscar o que esta **entre aspas**: e a unica forma
        # que aguenta o comentario do fim da linha sem lhe tocar -- um corte pelo
        # `;` comia tambem o `v=DKIM1; h=sha256;` do principio do valor. Os
        # pedacos juntam-se sem espaco entre eles (o base64 vem partido a meio) e
        # os espacos de dentro de cada pedaco ficam como estao, que e o que
        # separa `k=rsa;` de `p=`.
        $bruto = (Invoke-Vm "cat $caminhoChave").Output
        if ($bruto) {
            $pedacos = [regex]::Matches($bruto, '"([^"]*)"') | ForEach-Object { $_.Groups[1].Value }
            $valorDkim = ($pedacos -join '').Trim()
            $temChave = $true
            Write-Host ("  registo DKIM ({0} caracteres, {1} pedacos):" -f $valorDkim.Length, $pedacos.Count) -ForegroundColor Green
            Write-Host ''
            Write-Host "  Nome:  $Seletor._domainkey.$Dominio" -ForegroundColor White
            Write-Host "  Tipo:  TXT" -ForegroundColor White
            Write-Host "  Valor: $valorDkim" -ForegroundColor White
            Write-Host ''
        }
    }
}

# ---------------------------------------------------------------------------
# 2. O que devia estar publicado
# ---------------------------------------------------------------------------
$spf = "v=spf1 mx -all"
$dmarc = "v=DMARC1; p=none; rua=mailto:dmarc@$Dominio; adkim=s; aspf=s; fo=1"

# ---------------------------------------------------------------------------
# 3. O que esta publicado
# ---------------------------------------------------------------------------
Write-Host '=== 2. DNS publico ===' -ForegroundColor Cyan
Write-Host '  (via DNS-over-HTTPS: e o que um servidor de correio de fora ve)' -ForegroundColor DarkGray

$a = Resolve-Dns -Nome $Servidor -Tipo A
Check -O_Que "A $Servidor" -Ok ([bool]($a -contains $Ip)) `
    -Detalhe $(if ($a) { $a -join ', ' } else { 'sem registo' }) `
    -Sugestao "criar A $Servidor -> $Ip (sem isto nao ha certificado nem MX a funcionar)"

$mx = Resolve-Dns -Nome $Dominio -Tipo MX
Check -O_Que "MX $Dominio" -Ok ([bool](($mx | Where-Object { $_ -match [regex]::Escape($Servidor) }).Count)) `
    -Detalhe $(if ($mx) { $mx -join ' | ' } else { 'sem registo' }) `
    -Sugestao "criar MX @ -> 10 $Servidor. (sem isto o dominio nao recebe correio)"

$txt = Resolve-Dns -Nome $Dominio -Tipo TXT
$temSpf = [bool](($txt | Where-Object { $_ -match '^v=spf1' }).Count)
Check -O_Que "SPF $Dominio" -Ok $temSpf `
    -Detalhe $(if ($temSpf) { ($txt | Where-Object { $_ -match '^v=spf1' }) -join ' | ' } else { 'sem SPF' }) `
    -Sugestao "criar TXT @ -> `"$spf`" (autoriza a VM a enviar em nome do dominio)"

if ($temChave) {
    $dkim = Resolve-Dns -Nome "$Seletor._domainkey.$Dominio" -Tipo TXT
    $igual = [bool](($dkim | Where-Object { $_ -eq $valorDkim }).Count)
    Check -O_Que "DKIM $Seletor._domainkey" -Ok $igual `
        -Detalhe $(if (-not $dkim) { 'sem registo' } elseif ($igual) { 'bate com a chave da VM' } else { 'existe, mas nao bate com a chave da VM' }) `
        -Sugestao 'publicar o valor mostrado acima (ou a chave foi rodada e o DNS nao acompanhou)'
} else {
    Write-Host '  DKIM                   -- (sem chave da VM para comparar)' -ForegroundColor DarkGray
}

$d = Resolve-Dns -Nome "_dmarc.$Dominio" -Tipo TXT
Check -O_Que "DMARC _dmarc" -Ok ([bool](($d | Where-Object { $_ -match '^v=DMARC1' }).Count)) `
    -Detalhe $(if ($d) { $d -join ' | ' } else { 'sem registo' }) `
    -Sugestao "criar TXT _dmarc -> `"$dmarc`" (comecar em p=none; so apertar depois de ver os relatorios)"

# PTR: consulta-se o nome inverso do IP, que e o que os filtros de spam fazem.
$octetos = $Ip -split '\.'
[array]::Reverse($octetos)
$inverso = $octetos -join '.'
$ptr = Resolve-Dns -Nome "$inverso.in-addr.arpa" -Tipo PTR
Check -O_Que 'PTR (DNS inverso)' -Ok ([bool](($ptr | Where-Object { $_ -match [regex]::Escape($Servidor) }).Count)) `
    -Detalhe $(if ($ptr) { $ptr -join ', ' } else { 'sem PTR' }) `
    -Sugestao "pedir a Kamatera (suporte/consola) PTR $Ip -> $Servidor ; sem isto o correio vai para spam"

# ---------------------------------------------------------------------------
# 4. Resumo
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '=== 3. Registo para colar no DNS (Hostinger) ===' -ForegroundColor Cyan
Write-Host ("  {0,-7}{1,-22} {2}" -f 'A', $Servidor, $Ip)
Write-Host ("  {0,-7}{1,-22} {2}" -f 'MX', '@', "10 $Servidor.")
Write-Host ("  {0,-7}{1,-22} {2}" -f 'TXT', '@', $spf)
if ($temChave) {
    Write-Host ("  {0,-7}{1,-22} {2}" -f 'TXT', "$Seletor._domainkey", $valorDkim)
}
Write-Host ("  {0,-7}{1,-22} {2}" -f 'TXT', '_dmarc', $dmarc)
Write-Host ''
Write-Host "  Caixa de relatorios: $Postmaster (criar com" -ForegroundColor DarkGray
Write-Host "  `"docker exec -ti $Contentor setup email add $Postmaster`")" -ForegroundColor DarkGray

Write-Host ''
if ($problemas -eq 0) {
    Write-Host 'DNS DO CORREIO COMPLETO: SPF, DKIM, DMARC e PTR publicados e coerentes.' -ForegroundColor Green
} else {
    Write-Host "FALTAM $problemas COISA(S) NO DNS -- ver as linhas a vermelho acima." -ForegroundColor Red
    Write-Host 'Nota: uma alteracao de DNS pode levar minutos a propagar; repetir o script depois.' -ForegroundColor DarkGray
}
Write-Host ''
