#requires -Version 5.1
<#
.SYNOPSIS
    Envia uma pasta de dados do PC para a VM, sem tocar no codigo.

.DESCRIPTION
    O deploy de codigo exclui `data/` de proposito: sao ~37 GB de dados
    recolhidos, e nao faz sentido reenviar isso a cada mudanca de uma linha de
    Python. Mas ha subpastas de `data/` que sao a **fonte** de um modulo -- o
    `data/remuneracoes/` (~97 MB) e o exemplo: sem ele, as rotas respondem 200
    com tudo a zero, porque o servico le os JSON antes de tocar no Elasticsearch.

    Esse e o modo de falha que este script existe para resolver, e e traicoeiro:
    a rota responde, o `health` esta verde, e os numeros sao zero.

    Vai num **tar.gz unico pelo stdin do ssh** -- uma ligacao, sem limite de
    tamanho de linha de comando, e sem uma aspa pelo caminho. E a mesma tecnica
    do `00-push-edge-files.ps1`, pela mesma razao.

    Nao apaga nada do lado do destino: extrai por cima. Se um ficheiro tiver sido
    removido na origem, continua la -- para isso, limpar a pasta antes.

.PARAMETER Local
    Pasta no PC (ex.: `data\remuneracoes`).

.PARAMETER Destino
    Pasta na VM onde o conteudo deve ficar. O **conteudo** de `-Local` e extraido
    aqui, nao a pasta em si.

.EXAMPLE
    .\22-enviar-pasta.ps1 -Local data\remuneracoes -Dest /opt/iqos/servicos/backend/data/remuneracoes
    .\22-enviar-pasta.ps1 -Local data\remuneracoes -Dest ... -Verificar
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Local,
    [Parameter(Mandatory)][string]$Destino,

    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",

    # Compara o que esta la com o que vai ser enviado, e nao envia.
    [switch]$Verificar
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Local)) { throw "nao encontro $Local" }
$origem = (Resolve-Path $Local).Path

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$Comando)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & ssh -i $SshKey -o BatchMode=yes -o LogLevel=ERROR "$SshUser@$SshHost" $Comando 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

$ficheiros = @(Get-ChildItem $origem -Recurse -File)
$totalLocal = ($ficheiros | Measure-Object Length -Sum).Sum
Write-Host ''
Write-Host "=== $origem ===" -ForegroundColor Cyan
Write-Host ("  {0} ficheiros, {1:N1} MB locais" -f $ficheiros.Count, ($totalLocal / 1MB))
Write-Host ("  destino: $Destino")

# --- 1. O que falta do lado de la ------------------------------------------
# `find -printf '%P|%s'` com o caminho primeiro: o PowerShell come o `\r` do fim
# de cada linha, e com o tamanho no fim dois nomes que difiram so por um `\r`
# colidiam no dicionario. Ver o `00-push-edge-files.ps1`.
$listagem = (Invoke-Vm "find $Destino -type f -printf '%P|%s\n' 2>/dev/null || true").Output
$remotos = @{}
foreach ($linha in ($listagem -split "`n")) {
    if ("$linha" -match '^(.*)\|(\d+)$') { $remotos[$Matches[1]] = [int64]$Matches[2] }
}

$faltam = @(); $diferentes = @(); $iguais = 0
foreach ($f in $ficheiros) {
    $rel = $f.FullName.Substring($origem.Length).TrimStart('\').Replace('\', '/')
    if (-not $remotos.ContainsKey($rel)) { $faltam += $rel }
    elseif ($remotos[$rel] -ne $f.Length) { $diferentes += "$rel ($($remotos[$rel]) -> $($f.Length))" }
    else { $iguais++ }
}

Write-Host ''
Write-Host ("  ja na VM e iguais : {0}" -f $iguais)
if ($faltam.Count)     { Write-Host ("  em falta na VM    : {0}" -f $faltam.Count) -ForegroundColor Yellow }
if ($diferentes.Count) { Write-Host ("  tamanho diferente : {0}" -f $diferentes.Count) -ForegroundColor Yellow }

if ($Verificar) {
    if ($faltam.Count) { Write-Host ''; Write-Host '  ficheiros em falta (primeiros 20):' -ForegroundColor Yellow; $faltam | Select-Object -First 20 | ForEach-Object { Write-Host "    $_" } }
    if ($diferentes.Count) { Write-Host ''; Write-Host '  com tamanho diferente (primeiros 20):' -ForegroundColor Yellow; $diferentes | Select-Object -First 20 | ForEach-Object { Write-Host "    $_" } }
    Write-Host ''
    Write-Host '  (-Verificar: nao enviei nada)' -ForegroundColor DarkGray
    Write-Host ''
    return
}

# --- 2. Empacotar ----------------------------------------------------------
$tgz = Join-Path $env:TEMP 'iqos-pasta.tar.gz'
if (Test-Path $tgz) { Remove-Item $tgz -Force }

Write-Host ''
Write-Host '=== a empacotar ===' -ForegroundColor Cyan
# `-C $origem .` para o arquivo nao levar o caminho absoluto do PC la dentro.
& tar -czf $tgz -C $origem .
if ($LASTEXITCODE -ne 0) { throw "tar falhou (exit $LASTEXITCODE)" }
$tam = (Get-Item $tgz).Length
Write-Host ("  {0:N1} MB -> {1:N1} MB comprimido ({2:N0}%)" -f ($totalLocal / 1MB), ($tam / 1MB), (100 * $tam / $totalLocal))

# --- 3. Enviar -------------------------------------------------------------
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($tgz))
Write-Host ''
Write-Host '=== a enviar ===' -ForegroundColor Cyan
Write-Host ("  {0:N1} MB em base64, por uma so ligacao" -f ($b64.Length / 1MB))

# `tr -cd` antes do `base64 -d`: o PowerShell acrescenta uma mudanca de linha ao
# fechar o stdin e o `base64` do GNU avisa "invalid input" -- mesmo
# descodificando tudo certo. Filtrar ao alfabeto cala o aviso.
$remoto = "mkdir -p $Destino; tr -cd A-Za-z0-9+/= | base64 -d | tar -xzf - -C $Destino; echo extraido"
$b64 | & ssh -i $SshKey -o BatchMode=yes -o LogLevel=ERROR "$SshUser@$SshHost" $remoto
if ($LASTEXITCODE -ne 0) { throw "ssh falhou (exit $LASTEXITCODE)" }

# --- 4. Conferir -----------------------------------------------------------
Write-Host ''
Write-Host '=== a conferir ===' -ForegroundColor Cyan
$listagem = (Invoke-Vm "find $Destino -type f -printf '%P|%s\n'").Output
$remotos = @{}
foreach ($linha in ($listagem -split "`n")) {
    if ("$linha" -match '^(.*)\|(\d+)$') { $remotos[$Matches[1]] = [int64]$Matches[2] }
}

$maus = 0
foreach ($f in $ficheiros) {
    $rel = $f.FullName.Substring($origem.Length).TrimStart('\').Replace('\', '/')
    if (-not $remotos.ContainsKey($rel)) { Write-Host "  FALTA   $rel" -ForegroundColor Red; $maus++ }
    elseif ($remotos[$rel] -ne $f.Length) { Write-Host ("  TAMANHO {0}: local {1}, VM {2}" -f $rel, $f.Length, $remotos[$rel]) -ForegroundColor Red; $maus++ }
}

Write-Host ''
if ($maus -gt 0) { Write-Host "  $maus ficheiros com problema" -ForegroundColor Red; exit 1 }
Write-Host ("  {0} ficheiros confirmados na VM" -f $ficheiros.Count) -ForegroundColor Green
Write-Host ''
Write-Host '  Se for uma pasta montada num contentor, reinicie-o para ele ver os' -ForegroundColor DarkGray
Write-Host '  ficheiros novos (um bind mount ve o conteudo, mas a aplicacao pode ter' -ForegroundColor DarkGray
Write-Host '  carregado os dados para memoria no arranque).' -ForegroundColor DarkGray
Write-Host ''
