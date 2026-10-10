#requires -Version 5.1
<#
.SYNOPSIS
    Envia a pasta `edge/` para a VM Kamatera sem usar scp.

.DESCRIPTION
    Nesta rede o `scp` fica preso; este script usa o canal `ssh` que funciona.

    A pasta vai inteira num **tar.gz unico**, passado pelo stdin do ssh em
    base64: uma ligacao, um ficheiro, sem limite de tamanho de linha de comando.

    Porque nao ficheiro a ficheiro, que era o que aqui estava: duas razoes,
    ambas medidas.

      * A linha de comando do Windows acaba aos 32 KB. Os `img/*.png` da landing
        tem 100-210 KB, que em base64 dao ~280 KB cada -- o script morria com
        "The filename or extension is too long" antes de enviar o primeiro byte.
        Ou seja, nunca podia ter funcionado desde que os prints entraram.
      * Ja com o stdin como transporte, uma ligacao por ficheiro sao 17 ligacoes
        seguidas, e nesta rede uma delas caiu a meio ("Connection timed out", a
        7.a). O OpenSSH do Windows nao suporta multiplexing (`ControlMaster`),
        por isso nao havia como reutilizar a ligacao -- so reduzir o numero
        delas a uma.

    A conferencia e feita no fim: o tamanho de cada ficheiro local e comparado
    com o que o `find` remoto reporta. Tamanhos iguais nao provam bytes iguais,
    mas apanham o modo de falha que interessa -- um ficheiro truncado a meio
    pelo tar.

.EXAMPLE
    .\00-push-edge-files.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [string]$RemoteDir = '/opt/iqos'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here 'edge'
if (-not (Test-Path $src)) { throw "Nao encontro a pasta $src" }

$TmpTar = Join-Path $env:TEMP 'iqos-edge-push.tar.gz'

Write-Host ''
Write-Host "=== A empacotar $src ===" -ForegroundColor Cyan

# `-C $src .` para o arquivo nao levar o caminho absoluto do PC la dentro --
# assim extrai-se em qualquer lado com a mesma arvore relativa.
& tar -czf $TmpTar -C $src .
if ($LASTEXITCODE -ne 0) { throw "tar falhou (exit $LASTEXITCODE)" }

$bytes = (Get-Item $TmpTar).Length
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($TmpTar))
Write-Host ("  {0:N0} bytes -> {1:N0} em base64" -f $bytes, $b64.Length) -ForegroundColor DarkGray

# `tr -cd` antes do `base64 -d`: o PowerShell acrescenta uma mudanca de linha ao
# fechar o stdin e o `base64` do GNU queixa-se com "invalid input" -- mesmo
# descodificando tudo de forma correta, como se confirmou pelos hashes. Filtrar
# a entrada ao alfabeto base64 cala o aviso em vez de deixar ruido vermelho em
# cada publicacao, que e o que ensina a ignorar avisos a serio.
Write-Host ''
Write-Host "=== A enviar para $SshUser@$SshHost ===" -ForegroundColor Cyan
$remoto = "mkdir -p $RemoteDir/edge; tr -cd A-Za-z0-9+/= | base64 -d | tar -xzf - -C $RemoteDir/edge; echo extraido"
$b64 | & ssh -i $SshKey -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR "$SshUser@$SshHost" $remoto
if ($LASTEXITCODE -ne 0) { throw "ssh falhou (exit $LASTEXITCODE)" }

Write-Host ''
Write-Host '=== A conferir ===' -ForegroundColor Cyan

# `-printf '%P|%s'`: **o caminho primeiro e o tamanho depois**, de proposito.
#
# Ao ler a saida de um comando externo, o PowerShell parte-a em linhas e come o
# `\r` que esteja no fim de cada uma. Com `%s %P` o `\r` de um nome como
# `compose.yml\r` ficava no fim da linha, era comido, e a entrada colidia com a
# do `compose.yml` verdadeiro -- a boa era substituida no dicionario e a
# verificacao acusava um ficheiro truncado que estava perfeito. Foi exatamente o
# que aconteceu a primeira vez que isto correu. Com o tamanho no fim, o `\r`
# fica a meio da linha, chega intacto e a entrada com CR fica com chave propria.
$listagem = & ssh -i $SshKey -o BatchMode=yes -o LogLevel=ERROR "$SshUser@$SshHost" `
    "find $RemoteDir/edge -type f -printf '%P|%s\n'"
if ($LASTEXITCODE -ne 0) { throw "ssh falhou (exit $LASTEXITCODE)" }

$remotos = @{}
$comCr = New-Object System.Collections.Generic.List[string]
foreach ($linha in $listagem) {
    if ("$linha" -notmatch '^(.*)\|(\d+)$') { continue }
    $rel = $Matches[1]
    $remotos[$rel] = [int64]$Matches[2]
    if ($rel -match "[`r`n]") { $comCr.Add($rel) }
}

$enviados = 0
$maus = 0
foreach ($f in (Get-ChildItem -Path $src -Recurse -File)) {
    $rel = $f.FullName.Substring($src.Length).TrimStart('\').Replace('\', '/')
    if (-not $remotos.ContainsKey($rel)) {
        Write-Host "  FALTA      $rel" -ForegroundColor Red
        $maus++
    } elseif ($remotos[$rel] -ne $f.Length) {
        Write-Host ("  TAMANHO    {0}: local {1}, remoto {2}" -f $rel, $f.Length, $remotos[$rel]) -ForegroundColor Red
        $maus++
    } else {
        Write-Host ("  -> {0} ({1} bytes)" -f $rel, $f.Length)
        $enviados++
    }
}

# O que so existe na VM e informacao, nao erro: o `.env` (password do painel e
# origem do Caddy) e a pasta `data/` (registos da landing) nunca sao enviados
# daqui -- sao estado do servidor. Listar serve para se ver que continuam la.
$extras = @($remotos.Keys | Where-Object { -not (Test-Path (Join-Path $src $_)) })
if ($extras.Count) {
    Write-Host ''
    Write-Host '  (so na VM, esperado):' -ForegroundColor DarkGray
    foreach ($e in ($extras | Sort-Object)) { Write-Host "     $e" -ForegroundColor DarkGray }
}

if ($comCr.Count) {
    Write-Host ''
    Write-Host "  AVISO: $($comCr.Count) nomes no destino com retorno de carro no nome." -ForegroundColor Yellow
    Write-Host '         Nao foram escritos por este script e nenhuma ferramenta lhes toca,' -ForegroundColor Yellow
    Write-Host '         mas aparecem a quem percorra a pasta. Limpar com' -ForegroundColor Yellow
    Write-Host '         `deploy/kamatera/_limpar_nomes_cr.py` (simula por omissao).' -ForegroundColor Yellow
    foreach ($n in $comCr) { Write-Host ("         {0}" -f ($n -replace "[`r`n]", '<CR>')) -ForegroundColor Yellow }
}

Write-Host ''
if ($maus -gt 0) {
    Write-Host "  $maus ficheiros com problema -- ver acima" -ForegroundColor Red
    exit 1
}
Write-Host ("  {0} ficheiros confirmados, {1:N1} KB" -f $enviados, (($remotos.Values | Measure-Object -Sum).Sum / 1KB)) -ForegroundColor Green
Write-Host ''
