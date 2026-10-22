$vm = @{}
Get-Content 'C:\LLMFinance\_deploy_diag\_vm_indices.txt' |
    Where-Object { $_ -match "`t" -and $_ -notmatch '^__' } |
    ForEach-Object { $p = $_ -split "`t"; $vm[$p[0]] = [int]$p[1] }

$pc = @{}
Get-Content 'C:\LLMFinance\_deploy_diag\_pc_indices.txt' |
    Where-Object { $_ -match "`t" -and $_ -notmatch '^__' } |
    ForEach-Object { $p = $_ -split "`t"; $pc[$p[0]] = [int]$p[1] }

Write-Host "=== indices que existem so no PC (faltam na VM) ==="
$soPc = @($pc.Keys | Where-Object { -not $vm.ContainsKey($_) } | Sort-Object)
if ($soPc.Count -eq 0) {
    Write-Host "  (nenhum)"
} else {
    foreach ($i in $soPc) { "  {0,-38} {1,8} docs" -f $i, $pc[$i] }
}

Write-Host ""
Write-Host "=== indices que existem so na VM ==="
$soVm = @($vm.Keys | Where-Object { -not $pc.ContainsKey($_) } | Sort-Object)
if ($soVm.Count -eq 0) {
    Write-Host "  (nenhum)"
} else {
    foreach ($i in $soVm) { "  {0,-38} {1,8} docs" -f $i, $vm[$i] }
}

Write-Host ""
Write-Host "  PC: $($pc.Count) indices / VM: $($vm.Count) indices"

Write-Host ""
Write-Host "=== contagens diferentes (excluindo indices de estado/sessao) ==="
$vivos = @('finance_sessions','finance_users','finance_user_state','finance_events','finance_news',
           'finance_people','finance_prices','finance_scraped','finance_social','finance_sentiment_daily',
           'finance_publicacoes_mj','finance_crm_rbac','finance_world_investigations','finance_world_relations',
           'finance_entities','finance_racius')
$n = 0
foreach ($i in ($pc.Keys | Sort-Object)) {
    if (-not $vm.ContainsKey($i)) { continue }
    if ($pc[$i] -ne $vm[$i]) {
        $marca = if ($vivos -contains $i) { '  (vivo)' } else { '' }
        "  {0,-36} PC={1,9}  VM={2,9}  dif={3}{4}" -f $i, $pc[$i], $vm[$i], ($pc[$i] - $vm[$i]), $marca
        $n++
    }
}
if ($n -eq 0) { Write-Host "  (nenhuma)" }
