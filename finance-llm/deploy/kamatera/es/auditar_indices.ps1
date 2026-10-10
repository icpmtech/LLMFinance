# Audita todos os indices do Elasticsearch: PC vs VM.
#
# Compara, indice a indice: existencia, numero de documentos, tamanho em disco,
# numero de campos e -- o que interessa -- os campos cujo tipo difere ou que
# faltam num dos lados.
#
# Porque e que isto existe
# ------------------------
# A migracao deu "48 indices, 3,5 M documentos, tudo verde". Mas estar verde nao
# e estar completo:
#
#   - `contratos` e `contratos_es` foram criados VAZIOS (0 documentos) porque o
#     limite `MAX_MB` do `migrar.sh` os saltou por serem os maiores;
#   - e em `contratos` o mapeamento da VM tinha 42 campos contra 43 do PC --
#     faltava o `embedding`.
#
# Nenhuma dessas duas coisas aparece num `_cat/indices` verde. Este script
# apanha-as, e corre em segundos porque busca `/_mapping` e `/_stats` inteiros
# em vez de perguntar indice a indice.
#
#     .\auditar_indices.ps1
#     .\auditar_indices.ps1 -SoDiferencas
#     .\auditar_indices.ps1 -Csv > auditoria.csv

[CmdletBinding()]
param(
    [string] $EsPc = 'http://127.0.0.1:9200',
    [string] $EsVm = 'http://127.0.0.1:9200',
    [string] $TunnelContainer = 'iqos-origin-tunnel',
    [string] $SshUser = 'root',
    [string] $SshHost = '45.147.251.188',
    # Indices so de servico interno, que nao vale a pena comparar a serio.
    [string[]] $Ignorar = @(),
    [switch] $SoDiferencas,
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

$tmp = Join-Path $env:TEMP 'iqos-auditoria'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp | Out-Null

# --- recolha (uma chamada por lado, nao uma por indice) --------------------
# Sem `&` nos URLs de proposito: o `&` nao sobrevive bem a passagem
# PowerShell -> ssh. `_stats` com `filter_path` evita o `_cat/indices?h=..&format=json`.

Write-Host 'a buscar os mapeamentos e as contagens...' -ForegroundColor DarkGray

$stPc = Join-Path $tmp 'pc-stats.json'
$stVmLocal = Join-Path $tmp 'vm-stats.json'

curl.exe -s -o (Join-Path $tmp 'pc-map.json') "$EsPc/_mapping" | Out-Null
curl.exe -s -o $stPc "$EsPc/_stats/docs,store?filter_path=indices.*.primaries.docs.count,indices.*.primaries.store.size_in_bytes" | Out-Null

$vmMap = Invoke-Vm "curl -s $EsVm/_mapping"
$vmSt = Invoke-Vm "curl -s $EsVm/_stats/docs,store?filter_path=indices.*.primaries.docs.count,indices.*.primaries.store.size_in_bytes"

if ($vmMap.Output -notmatch '\{') { throw 'a VM nao devolveu mapeamentos (o ES esta de pe?)' }
if ($vmSt.Output -notmatch '\{') { throw 'a VM nao devolveu estatisticas' }

$vmMap.Output | Set-Content -Encoding UTF8 (Join-Path $tmp 'vm-map.json')
$vmSt.Output | Set-Content -Encoding UTF8 $stVmLocal

$mapPc = Get-Content (Join-Path $tmp 'pc-map.json') -Raw | ConvertFrom-Json
$mapVm = Get-Content (Join-Path $tmp 'vm-map.json') -Raw | ConvertFrom-Json
$statsPc = (Get-Content $stPc -Raw | ConvertFrom-Json).indices
$statsVm = (Get-Content $stVmLocal -Raw | ConvertFrom-Json).indices

$indicesPc = @($mapPc.PSObject.Properties.Name | Sort-Object)
$indicesVm = @($mapVm.PSObject.Properties.Name | Sort-Object)

$linhas = @()

foreach ($idx in $indicesPc) {
    if ($Ignorar -contains $idx) { continue }

    $docsPc = 0; $bytesPc = 0
    if ($statsPc.PSObject.Properties.Name -contains $idx) {
        $s = $statsPc.$idx.primaries
        if ($s) { $docsPc = [int64]$s.docs.count; $bytesPc = [int64]$s.store.size_in_bytes }
    }

    $existeVm = $indicesVm -contains $idx
    $docsVm = -1; $bytesVm = 0
    if ($existeVm) {
        if ($statsVm.PSObject.Properties.Name -contains $idx) {
            $s = $statsVm.$idx.primaries
            if ($s) { $docsVm = [int64]$s.docs.count; $bytesVm = [int64]$s.store.size_in_bytes }
        } else {
            $docsVm = 0
        }
    }

    $camposPc = 0; $camposVm = 0
    $soPc = @(); $soVm = @(); $tiposDif = @()

    $propsPc = @($mapPc.$idx.mappings.properties.PSObject.Properties.Name)
    $camposPc = $propsPc.Count

    if ($existeVm) {
        $propsVm = @($mapVm.$idx.mappings.properties.PSObject.Properties.Name)
        $camposVm = $propsVm.Count
        $soPc = @(Compare-Object $propsPc $propsVm |
            Where-Object { $_.SideIndicator -eq '<=' } | Select-Object -ExpandProperty InputObject)
        $soVm = @(Compare-Object $propsPc $propsVm |
            Where-Object { $_.SideIndicator -eq '=>' } | Select-Object -ExpandProperty InputObject)
        foreach ($p in ($propsPc | Where-Object { $propsVm -contains $_ })) {
            $tp = $mapPc.$idx.mappings.properties.$p.type
            $tv = $mapVm.$idx.mappings.properties.$p.type
            if ($tp -ne $tv) { $tiposDif += "$p($tp/$tv)" }
        }
    }

    # Campo de nivel superior cujo tipo mais gente usa. `text` vs `keyword` e a
    # divergencia classica e parte as pesquisas sem dar erro nenhum.
    $divergente = (-not $existeVm) -or ($docsPc -ne $docsVm) -or
                  ($soPc.Count -gt 0) -or ($soVm.Count -gt 0) -or ($tiposDif.Count -gt 0)

    $linhas += [PSCustomObject]@{
        Indice      = $idx
        DocsPC      = $docsPc
        DocsVM      = $(if ($existeVm) { $docsVm } else { -1 })
        FaltamDocs  = $(if ($existeVm) { $docsPc - $docsVm } else { $docsPc })
        CamposPC    = $camposPc
        CamposVM    = $(if ($existeVm) { $camposVm } else { -1 })
        SoNoPC      = ($soPc -join ',')
        SoNaVM      = ($soVm -join ',')
        TiposDif    = ($tiposDif -join ',')
        Divergente  = $divergente
    }
}

foreach ($idx in $indicesVm) {
    if ($indicesPc -contains $idx) { continue }
    if ($Ignorar -contains $idx) { continue }
    $s = $statsVm.$idx.primaries
    $linhas += [PSCustomObject]@{
        Indice = $idx
        DocsPC = -1; DocsVM = [int64]$s.docs.count; FaltamDocs = -1
        CamposPC = -1; CamposVM = @($mapVm.$idx.mappings.properties.PSObject.Properties.Name).Count
        SoNoPC = ''; SoNaVM = ''; TiposDif = ''
        Divergente = $true
    }
}

$linhas = $linhas | Sort-Object Indice
$divergentes = @($linhas | Where-Object { $_.Divergente })

if ($Csv) {
    $linhas | ConvertTo-Csv -NoTypeInformation
    return
}

# --- tabela ---------------------------------------------------------------
$mostrar = if ($SoDiferencas) { $divergentes } else { $linhas }

$totPc = ($linhas | Where-Object { $_.DocsPC -gt 0 } | Measure-Object DocsPC -Sum).Sum
$totVm = ($linhas | Where-Object { $_.DocsVM -gt 0 } | Measure-Object DocsVM -Sum).Sum

Write-Host ''
Write-Host '=== Indices ===' -ForegroundColor Cyan
# Sem `r = 1` nos hashtables: o alinhamento a direita por campo so existe no
# PowerShell 7. No 5.1 o `Format-Table` rejeita a chave com
# "The r key is not valid".
$mostrar | Format-Table -AutoSize `
    @{ n = 'indice'; e = { $_.Indice } },
    @{ n = 'docs PC'; e = { if ($_.DocsPC -lt 0) { '-' } else { '{0:N0}' -f $_.DocsPC } } },
    @{ n = 'docs VM'; e = { if ($_.DocsVM -lt 0) { 'nao existe' } else { '{0:N0}' -f $_.DocsVM } } },
    @{ n = 'faltam'; e = { if ($_.FaltamDocs -le 0) { '' } else { '{0:N0}' -f $_.FaltamDocs } } },
    @{ n = 'campos'; e = { '{0}/{1}' -f $_.CamposPC, $_.CamposVM } },
    @{ n = 'campos so no PC'; e = { $_.SoNoPC } },
    @{ n = 'campos so na VM'; e = { $_.SoNaVM } },
    @{ n = 'tipos diferentes'; e = { $_.TiposDif } }

Write-Host ''
Write-Host '=== Resumo ===' -ForegroundColor Cyan
Write-Host ("  indices no PC        : {0}" -f $indicesPc.Count)
Write-Host ("  indices na VM        : {0}" -f $indicesVm.Count)
Write-Host ("  divergentes          : {0}" -f $divergentes.Count) -ForegroundColor $(if ($divergentes.Count) { 'Yellow' } else { 'Green' })
Write-Host ("  documentos no PC     : {0:N0}" -f $totPc)
Write-Host ("  documentos na VM     : {0:N0}" -f $totVm)
Write-Host ("  documentos em falta  : {0:N0}" -f ($totPc - $totVm)) -ForegroundColor $(if (($totPc - $totVm) -gt 0) { 'Yellow' } else { 'Green' })
