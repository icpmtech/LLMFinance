function Get-Json($url) {
    try {
        $c = (Invoke-WebRequest -Uri $url -TimeoutSec 60 -UseBasicParsing).Content
        return @{ ok = $true; bytes = $c.Length; json = ($c | ConvertFrom-Json) }
    } catch {
        return @{ ok = $false; erro = $_.Exception.Message }
    }
}

$B = @{
    local = 'http://127.0.0.1:8002'
    vm    = 'https://sabemos.studio/api'
}

Write-Host "########## /cms/posts ##########"
foreach ($k in 'local', 'vm') {
    $r = Get-Json "$($B[$k])/cms/posts"
    if (-not $r.ok) { Write-Host "  $k FALHA: $($r.erro)"; continue }
    $j = $r.json
    Write-Host "  --- $k ($($r.bytes) B) ---"
    $itens = $j.items
    if (-not $itens) { $itens = $j.posts }
    if (-not $itens) { Write-Host "    chaves: $($j.PSObject.Properties.Name -join ', ')"; $itens = @() }
    Write-Host "    total: $($j.total)   itens: $(@($itens).Count)"
    foreach ($p in @($itens)) {
        "      {0,-26} {1,-9} {2,-52}" -f $p.id, $p.status, $p.title
    }
}

Write-Host ""
Write-Host "########## post_8b984e2e4355 ##########"
$post = @{}
foreach ($k in 'local', 'vm') {
    $r = Get-Json "$($B[$k])/cms/posts/post_8b984e2e4355"
    if (-not $r.ok) { Write-Host "  $k FALHA: $($r.erro)"; continue }
    $post[$k] = $r.json
    Write-Host "  --- $k ($($r.bytes) B) ---"
    $j = $r.json
    foreach ($f in $j.PSObject.Properties.Name) {
        $v = $j.$f
        $s = if ($null -eq $v) { '(null)' } elseif ($v -is [array]) { "[array $($v.Count)]" } elseif ($v -is [PScriptBlock]) { '[obj]' } elseif ($v -is [PSCustomObject]) { "[obj $($v.PSObject.Properties.Name.Count) campos]" } else { "$v" }
        "      {0,-18} {1}" -f $f, $s.Substring(0, [Math]::Min(72, $s.Length))
    }
}

if ($post.local -and $post.vm) {
    Write-Host ""
    Write-Host "########## diferencas campo a campo ##########"
    $pl = @($post.local.PSObject.Properties.Name)
    $pv = @($post.vm.PSObject.Properties.Name)
    $campos = $pl + $pv | Sort-Object -Unique
    $dif = 0
    foreach ($f in $campos) {
        $a = $post.local.$f
        $b = $post.vm.$f
        $ja = if ($null -eq $a) { '' } else { $a | ConvertTo-Json -Depth 8 -Compress }
        $jb = if ($null -eq $b) { '' } else { $b | ConvertTo-Json -Depth 8 -Compress }
        if ($ja -ne $jb) {
            $dif++
            Write-Host "  DIFERE: $f"
            Write-Host "    local: $(if ($ja.Length -gt 220) { $ja.Substring(0,220) + '...' } else { $ja })"
            Write-Host "    vm   : $(if ($jb.Length -gt 220) { $jb.Substring(0,220) + '...' } else { $jb })"
        }
    }
    Write-Host ""
    Write-Host "  $dif campos diferentes de $($campos.Count)"
}
