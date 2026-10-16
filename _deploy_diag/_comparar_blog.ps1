$id = 'post_8b984e2e4355'
$localUrl = "http://127.0.0.1:8002/cms/blog/$id"
$vmUrl = "https://sabemos.studio/api/cms/blog/$id"

Write-Host "=== LOCAL: $localUrl ==="
$L = $null
try {
    $c = (Invoke-WebRequest -Uri $localUrl -TimeoutSec 60 -UseBasicParsing).Content
    $L = $c | ConvertFrom-Json
    "  OK  {0} B" -f $c.Length
} catch {
    "  FALHA: $($_.Exception.Message)"
}

Write-Host "=== VM: $vmUrl ==="
$V = $null
try {
    $c = (Invoke-WebRequest -Uri $vmUrl -TimeoutSec 60 -UseBasicParsing).Content
    $V = $c | ConvertFrom-Json
    "  OK  {0} B" -f $c.Length
} catch {
    "  FALHA: $($_.Exception.Message)"
}

if (-not $L -or -not $V) { Write-Host "`n  sem comparacao possivel"; exit 0 }

$campos = @($L.PSObject.Properties.Name) + @($V.PSObject.Properties.Name) | Sort-Object -Unique

Write-Host ""
Write-Host "=== campos ($($campos.Count)) ==="
$soLocal = @($L.PSObject.Properties.Name) | Where-Object { $campos -notcontains $_ }
$soVm = @($V.PSObject.Properties.Name) | Where-Object { $campos -notcontains $_ }
Write-Host "  so no local: $(if ($soLocal) { $soLocal -join ', ' } else { '(nenhum)' })"
Write-Host "  so na VM  : $(if ($soVm) { $soVm -join ', ' } else { '(nenhum)' })"

Write-Host ""
Write-Host "=== campo a campo ==="
$dif = 0
foreach ($f in $campos) {
    $a = $L.$f
    $b = $V.$f
    $sa = if ($null -eq $a) { '(null)' } elseif ($a -is [array]) { "[array $($a.Count)]" } elseif ($a -is [PSCustomObject]) { '[obj]' } else { "$a" }
    $sb = if ($null -eq $b) { '(null)' } elseif ($b -is [array]) { "[array $($b.Count)]" } elseif ($b -is [PSCustomObject]) { '[obj]' } else { "$b" }
    $igual = if ($sa -eq $sb) { 'IGUAL ' } else { 'DIFERE' }
    if ($igual -eq 'DIFERE') { $dif++ }
    "{0,-18} {1}  L={2,-30} V={3}" -f $f, $igual, $sa.Substring(0, [Math]::Min(30, $sa.Length)), $sb.Substring(0, [Math]::Min(30, $sb.Length))
}
Write-Host ""
Write-Host "  $dif campos diferentes de $($campos.Count)"
