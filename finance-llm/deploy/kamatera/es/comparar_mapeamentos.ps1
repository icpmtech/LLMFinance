# Compara os mapeamentos e as settings de indices entre o ES do PC e o da VM.
#
# Porque e que isto existe
# ------------------------
# A migracao criou os indices todos na VM a partir dos mapeamentos de origem,
# mas os dois indices maiores (`contratos`, `contratos_es`) ficaram **vazios**:
# o limite `MAX_MB` do `migrar.sh` saltou-os por serem os maiores. Um indice vazio
# "parece" migrado e nao esta -- e se o mapeamento dele tambem nao estiver
# correto, um `_bulk` de milhoes de documentos cria um indice errado em silencio.
#
# Foi exatamente isto que este script apanhou: em `contratos`, o campo
# `embedding` existia no PC e nao na VM.
#
#     .\comparar_mapeamentos.ps1
#     .\comparar_mapeamentos.ps1 -Indices contratos,contratos_es
#     .\comparar_mapeamentos.ps1 -Csv   # saida maquina-a-maquina

[CmdletBinding()]
param(
    [string[]] $Indices = @('contratos', 'contratos_es'),
    [string] $EsPc = 'http://127.0.0.1:9200',
    [string] $EsVm = 'http://127.0.0.1:9200',
    [string] $TunnelContainer = 'iqos-origin-tunnel',
    [string] $SshUser = 'root',
    [string] $SshHost = '45.147.251.188',
    [switch] $Csv
)

$ErrorActionPreference = 'Stop'

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

$tmp = Join-Path $env:TEMP 'iqos-mapeamentos'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp | Out-Null

$linhas = @()

foreach ($idx in $Indices) {

    # --- buscar os dois lados ---------------------------------------------
    $pcMapFile = Join-Path $tmp "pc-$idx-mapping.json"
    $pcSetFile = Join-Path $tmp "pc-$idx-settings.json"
    cmd.exe /c "curl.exe -s -o `"$pcMapFile`" `"$EsPc/$idx/_mapping`"" | Out-Null
    cmd.exe /c "curl.exe -s -o `"$pcSetFile`" `"$EsPc/$idx/_settings`"" | Out-Null

    $vmMap = Invoke-Vm "curl -s -o /tmp/iqos-map.json $EsVm/$idx/_mapping; cat /tmp/iqos-map.json; rm -f /tmp/iqos-map.json"
    $vmSet = Invoke-Vm "curl -s -o /tmp/iqos-set.json $EsVm/$idx/_settings; cat /tmp/iqos-set.json; rm -f /tmp/iqos-set.json"

    if (-not (Test-Path $pcMapFile) -or (Get-Item $pcMapFile).Length -eq 0) {
        Write-Host "  $idx : o PC nao devolveu mapeamento (o indice existe?)" -ForegroundColor Yellow
        continue
    }
    if ($vmMap.Output -notmatch '\{') {
        Write-Host "  $idx : a VM nao devolveu mapeamento" -ForegroundColor Yellow
        continue
    }

    $pcRaw = Get-Content $pcMapFile -Raw
    $vmRaw = $vmMap.Output
    ($vmRaw) | Set-Content -Encoding UTF8 (Join-Path $tmp "vm-$idx-mapping.json")

    $pc = $pcRaw | ConvertFrom-Json
    $vm = $vmRaw | ConvertFrom-Json

    $pcProps = @($pc.$idx.mappings.properties.PSObject.Properties.Name)
    $vmProps = @($vm.$idx.mappings.properties.PSObject.Properties.Name)

    $soPc = @(Compare-Object $pcProps $vmProps |
        Where-Object { $_.SideIndicator -eq '<=' } | Select-Object -ExpandProperty InputObject)
    $soVm = @(Compare-Object $pcProps $vmProps |
        Where-Object { $_.SideIndicator -eq '=>' } | Select-Object -ExpandProperty InputObject)

    # Campos cujo tipo difere sao tao perigosos como campos em falta: um campo
    # que e `keyword` num lado e `text` no outro muda os resultados de pesquisa.
    $tiposDiferentes = @()
    foreach ($p in ($pcProps | Where-Object { $vmProps -contains $_ })) {
        $tp = $pc.$idx.mappings.properties.$p.type
        $tv = $vm.$idx.mappings.properties.$p.type
        if ($tp -ne $tv) { $tiposDiferentes += "$p ($tp -> $tv)" }
    }

    # --- settings que afetam a pesquisa -----------------------------------
    $pcSet = Get-Content $pcSetFile -Raw | ConvertFrom-Json
    $vmSet = $vmSet.Output | ConvertFrom-Json
    $pcShards = $pcSet.$idx.settings.index.number_of_shards
    $vmShards = $vmSet.$idx.settings.index.number_of_shards
    $pcAnalyzer = $pcSet.$idx.settings.index.analysis.analyzer.PSObject.Properties.Name
    $vmAnalyzer = $vmSet.$idx.settings.index.analysis.analyzer.PSObject.Properties.Name

    if ($Csv) {
        $linhas += [PSCustomObject]@{
            indice      = $idx
            campos_pc   = $pcProps.Count
            campos_vm   = $vmProps.Count
            so_pc       = ($soPc -join '|')
            so_vm       = ($soVm -join '|')
            tipos_dif   = ($tiposDiferentes -join '|')
            shards_pc   = $pcShards
            shards_vm   = $vmShards
            analisadores = (@($pcAnalyzer).Count.ToString() + '/' + @($vmAnalyzer).Count.ToString())
            igual       = (($soPc.Count -eq 0) -and ($soVm.Count -eq 0) -and ($tiposDiferentes.Count -eq 0))
        }
        continue
    }

    Write-Host ''
    Write-Host "===== $idx =====" -ForegroundColor Cyan
    Write-Host ("  campos        : PC={0}  VM={1}" -f $pcProps.Count, $vmProps.Count)

    if ($soPc.Count -gt 0) {
        Write-Host ("  SO NO PC ({0})  : {1}" -f $soPc.Count, ($soPc -join ', ')) -ForegroundColor Red
    }
    if ($soVm.Count -gt 0) {
        Write-Host ("  SO NA VM ({0})  : {1}" -f $soVm.Count, ($soVm -join ', ')) -ForegroundColor Yellow
    }
    if ($tiposDiferentes.Count -gt 0) {
        Write-Host ("  TIPOS DIFERENTES: {0}" -f ($tiposDiferentes -join ', ')) -ForegroundColor Red
    }
    if ($soPc.Count -eq 0 -and $soVm.Count -eq 0 -and $tiposDiferentes.Count -eq 0) {
        Write-Host '  mapeamento    : identico' -ForegroundColor Green
    }

    $embPc = $pc.$idx.mappings.properties.embedding
    $embVm = $vm.$idx.mappings.properties.embedding
    Write-Host ("  embedding     : PC={0}  VM={1}" -f `
        (if ($embPc) { "$($embPc.type)/$($embPc.dims)" } else { 'ausente' }), `
        (if ($embVm) { "$($embVm.type)/$($embVm.dims)" } else { 'ausente' }))

    Write-Host ("  shards        : PC={0}  VM={1}" -f $pcShards, $vmShards)
    Write-Host ("  analisadores  : PC={0}  VM={1}" -f @($pcAnalyzer).Count, @($vmAnalyzer).Count)
}

if ($Csv) { $linhas | ConvertTo-Csv -NoTypeInformation }
