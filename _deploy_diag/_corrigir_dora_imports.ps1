$f = 'C:\LLMFinance\finance-llm\chat-ui\src\pages\DoraPage.tsx'

$enc = New-Object System.Text.UTF8Encoding($false)
$linhas = [System.IO.File]::ReadAllLines($f, [System.Text.Encoding]::UTF8)

Write-Host "=== antes: linhas 6 e 7 ==="
Write-Host ("  6: " + $linhas[5])
Write-Host ("  7: " + $linhas[6])

# Bloco novo (8 linhas) substitui o antigo bloco react+lucide (linhas 6..23 = indices 5..22)
$novo = @(
    'import { useCallback, useEffect, useState } from "react";'
    'import {'
    '  AlertTriangle,'
    '  BookOpen,'
    '  FileText,'
    '  Layers,'
    '  Loader2,'
    '  Plus,'
    '  RefreshCw,'
    '  Search,'
    '  ShieldAlert,'
    '  ShieldCheck,'
    '  Workflow,'
    '} from "lucide-react";'
)

# Confirma que o bloco antigo e o que esperamos.
if ($linhas[5] -notmatch 'useMemo' -or $linhas[22] -notmatch 'lucide-react') {
    Write-Host "ABORTA: o bloco nao esta onde esperava." -ForegroundColor Red
    Write-Host ("  linha 6  : " + $linhas[5])
    Write-Host ("  linha 23 : " + $linhas[22])
    exit 1
}

$resultado = @()
$resultado += $linhas[0..4]        # linhas 1-5
$resultado += $novo                 # novo bloco
$resultado += $linhas[23..($linhas.Count - 1)]   # da linha 24 em diante

[System.IO.File]::WriteAllLines($f, $resultado, $enc)
Write-Host ""
Write-Host "  escrito: $((Get-Item $f).Length) bytes"

Write-Host ""
Write-Host "=== depois: linhas 1-26 ==="
$depois = [System.IO.File]::ReadAllLines($f, [System.Text.Encoding]::UTF8)
for ($i = 0; $i -lt [Math]::Min(26, $depois.Count); $i++) {
    "{0,3}: {1}" -f ($i + 1), $depois[$i]
}
