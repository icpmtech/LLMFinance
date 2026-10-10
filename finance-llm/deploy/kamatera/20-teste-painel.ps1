#requires -Version 5.1
<#
.SYNOPSIS
    Renderiza o painel localmente, com dados reais, para se ver o que desenha.

.DESCRIPTION
    O `19-validar-monitor.ps1` prova que a API responde e devolve dados. Nao
    prova que o painel os **mostra** -- entre a resposta e o ecra estao o
    `app.js` e o `app.css`, e um erro de nomes de campo (ler `servico.nome`
    quando a API devolve `servico.name`) da uma pagina em branco com `/api/estado`
    a responder 200 e o `healthz` a dizer que esta tudo bem.

    Este script fecha esse intervalo:

      1. entra no painel pelo dominio e guarda o JSON de `/api/estado` (a
         password vem do `monitor-password.txt` e nunca aparece no ecra);
      2. copia o `index.html`, `app.css` e `app.js` **verdadeiros** para uma
         pasta de teste;
      3. injeta um stub que substitui o `fetch` pelo JSON guardado;
      4. deixa a pasta pronta a abrir no browser.

    O stub serve as duas rotas que a interface usa:
      * `GET /api/sessao` -> `{autenticado: true}`, para mostrar o painel em vez
        do formulario;
      * `GET /api/estado` -> o JSON real, capturado agora.

    Nada aqui toca na VM nem no servidor: os ficheiros sao os mesmos, mas
    servidos de disco.

.EXAMPLE
    .\20-teste-painel.ps1
    # depois abrir _teste_painel/index.html no browser
#>
[CmdletBinding()]
param(
    [string]$Base = 'https://sabemos.studio/monitor',
    [string]$FicheiroPassword
)

$ErrorActionPreference = 'Stop'
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $FicheiroPassword) { $FicheiroPassword = Join-Path $aqui 'monitor-password.txt' }
if (-not (Test-Path $FicheiroPassword)) { throw "Nao encontro $FicheiroPassword" }
$password = (Get-Content -Raw $FicheiroPassword).Trim()

$origem = Join-Path $aqui 'edge\monitor'
$destino = Join-Path $aqui '_teste_painel'

if (-not (Test-Path (Join-Path $origem 'app.js'))) { throw "Nao encontro o monitor em $origem" }

Write-Host ''
Write-Host '=== A capturar /api/estado do servidor ===' -ForegroundColor Cyan

$tmp = [IO.Path]::GetTempFileName()
$jar = Join-Path $env:TEMP 'iqos-monitor-teste-cookies.txt'
if (Test-Path $jar) { Remove-Item $jar -Force }

try {
    [IO.File]::WriteAllText($tmp, (@{ password = $password } | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
    $login = & curl.exe -s -o NUL -w '%{http_code}' --max-time 25 -X POST `
        -H 'Content-Type: application/json' --data-binary "@$tmp" -c $jar "$Base/api/login" 2>$null
    if ($login -ne '200') { throw "login falhou (HTTP $login)" }

    $estado = & curl.exe -s --max-time 30 -b $jar "$Base/api/estado" 2>$null
    if (-not $estado) { throw 'resposta vazia de /api/estado' }
    $parsed = $estado | ConvertFrom-Json
    Write-Host ("  {0} servicos, {1} imagens" -f @($parsed.servicos).Count, @($parsed.imagens).Count) -ForegroundColor DarkGray
} finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    Remove-Item $jar -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host '=== A montar a pasta de teste ===' -ForegroundColor Cyan

if (Test-Path $destino) { Remove-Item $destino -Recurse -Force }
New-Item -ItemType Directory -Path $destino | Out-Null

foreach ($f in @('app.css', 'app.js')) {
    Copy-Item (Join-Path $origem $f) (Join-Path $destino $f) -Force
    Write-Host "  copiado $f" -ForegroundColor DarkGray
}

# O JSON vai **embutido** no stub, e nao em `estado.json` para o stub ir buscar
# por `fetch`. A pagina e aberta por `file://`, e nesse contexto o Chrome recusa
# qualquer `fetch` a um caminho relativo (origem `null`). Ficaria um erro de CORS
# a parecer um problema do painel.
$stub = @"
// Substitui o ``fetch`` para o painel correr de disco, com os dados reais
// capturados agora do servidor de producao.
//
// Mantem a mesma forma da API -- JSON, e o campo ``autenticado`` na sessao --
// para o ``app.js`` percorrer exatamente os mesmos caminhos de codigo que
// percorreria ligado ao servidor. Um stub mais permissivo testava o stub.
const ESTADO_REAL = $estado;

const resposta = (corpo, status = 200) => Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(corpo),
    text: () => Promise.resolve(JSON.stringify(corpo)),
});

window.fetch = function (recurso) {
    const url = typeof recurso === 'string' ? recurso : (recurso && recurso.url) || '';
    if (url.indexOf('/api/sessao') !== -1)  { return resposta({ autenticado: true }); }
    if (url.indexOf('/api/estado') !== -1)  { return resposta(ESTADO_REAL); }
    if (url.indexOf('/api/logout') !== -1)  { return resposta({ ok: true }); }
    return resposta({ erro: 'rota nao simulada: ' + url }, 404);
};
"@

[IO.File]::WriteAllText((Join-Path $destino '_stub.js'), $stub, [Text.UTF8Encoding]::new($false))

# O `index.html` verdadeiro, com o stub injetado **antes** do `app.js`. Sao dois
# scripts classicos, sem `defer`, por isso a ordem de execucao e a do documento.
$html = [IO.File]::ReadAllText((Join-Path $origem 'index.html'))
$antes = '<script src="app.js"></script>'
if ($html.IndexOf($antes) -lt 0) { throw "nao encontro '$antes' no index.html" }
$html = $html.Replace($antes, '<script src="_stub.js"></script>' + "`n" + $antes)
[IO.File]::WriteAllText((Join-Path $destino 'index.html'), $html, [Text.UTF8Encoding]::new($false))

Write-Host '  index.html com o stub injetado' -ForegroundColor DarkGray

Write-Host ''
Write-Host "  Abrir: $(Join-Path $destino 'index.html')" -ForegroundColor Green
Write-Host ''
