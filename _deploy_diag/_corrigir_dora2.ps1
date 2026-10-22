$f = 'C:\LLMFinance\finance-llm\chat-ui\src\pages\DoraPage.tsx'
$enc = New-Object System.Text.UTF8Encoding($false)

$texto = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
$antes = $texto.Length
$feitos = @()

function Substituir {
    param([string]$Padrao, [string]$Novo, [string]$Nome)
    $script:texto = [regex]::Replace($script:texto, $Padrao, $Novo, 1)
    if ($script:texto.Length -ne $script:lenAnterior) {
        $script:feitos += $Nome
        $script:lenAnterior = $script:texto.Length
    } else {
        $script:feitos += "NAO APLICADO: $Nome"
    }
}

$script:lenAnterior = $texto.Length

# 1. Search nao usado
Substituir '  RefreshCw,\r?\n  Search,\r?\n  ShieldAlert,' "  RefreshCw,`r`n  ShieldAlert," 'remover Search'

# 2. DoraConteudoIdioma -> DoraConteudo
Substituir 'import type \{\r?\n  DoraConteudoIdioma,' "import type {`r`n  DoraConteudo," 'DoraConteudoIdioma -> DoraConteudo'

# 3. ingestDoraConteudo nao usado
Substituir '  ingestDoraConteudo,\r?\n' '' 'remover ingestDoraConteudo'

# 4. total nao lido
Substituir 'const \[total, setTotal\] = useState\(0\);' 'const [, setTotal] = useState(0);' 'total -> _'

# 5. acesso ao idioma
Substituir 'const c = conteudo\?\.\[idioma\];' 'const c = idioma === "pt" ? conteudo?.pt : conteudo?.original;' 'acesso ao idioma'

[System.IO.File]::WriteAllText($f, $texto, $enc)

Write-Host "=== substituicoes ==="
foreach ($x in $feitos) { Write-Host "  $x" }
Write-Host ""
Write-Host "  $antes -> $($texto.Length) bytes"

Write-Host ""
Write-Host "=== verificacao ==="
$d = [System.IO.File]::ReadAllLines($f, [System.Text.Encoding]::UTF8)
Write-Host "  useMemo presente?      $([bool]($d -match 'useMemo'))"
Write-Host "  Bot presente?          $([bool]($d -match '^\s+Bot,$'))"
Write-Host "  Search presente?       $([bool]($d -match '^\s+Search,$'))"
Write-Host "  DoraConteudoIdioma?    $([bool]($d -match 'DoraConteudoIdioma'))"
Write-Host "  DoraConteudo (import)? $([bool]($d -match '^\s+DoraConteudo,$'))"
Write-Host "  ingestDoraConteudo?    $([bool]($d -match 'ingestDoraConteudo'))"
Write-Host "  acesso ao idioma       $([bool]($d -match 'idioma === "pt"'))"
