#requires -Version 5.1
<#
.SYNOPSIS
    Valida o painel de estado do sistema ponta a ponta, pelo dominio publico.

.DESCRIPTION
    Verifica o que interessa, por esta ordem:

      1. a rota responde pelo dominio (`/monitor/healthz`);
      2. `http://` e `https://` sem barra final redireccionam para `/monitor/`
         -- e isto que faz os caminhos relativos do HTML resolverem dentro do
         prefixo, em vez de caírem na raiz do site;
      3. os ficheiros estaticos carregam (sem eles o painel fica branco e o
         `healthz` continua a dizer 200 -- por isso e que nao basta o ponto 1);
      4. **sem sessao**, `/api/estado` responde 401. Se respondesse 200, o
         painel estaria a mostrar o estado do servidor a quem passasse;
      5. com password errada, o login e recusado;
      6. com a password certa, o login passa e `/api/estado` devolve dados a
         serio: contentores, imagens e metricas da maquina.

    Le a password de `monitor-password.txt`, ao lado deste script, e **nao a
    imprime** -- nem no sucesso nem no falhanco.

.EXAMPLE
    .\19-validar-monitor.ps1
#>
[CmdletBinding()]
param(
    [string]$Base = 'https://sabemos.studio/monitor',
    [string]$FicheiroPassword,

    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519"
)

$ErrorActionPreference = 'Stop'

if (-not $FicheiroPassword) {
    $FicheiroPassword = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'monitor-password.txt'
}
if (-not (Test-Path $FicheiroPassword)) {
    throw "Nao encontro $FicheiroPassword -- correr o 18-monitor-env.ps1 primeiro."
}
$password = (Get-Content -Raw $FicheiroPassword).Trim()

$falhas = New-Object System.Collections.Generic.List[string]

function Ok    { param([string]$t) Write-Host "  OK    $t" -ForegroundColor Green }
function Falha { param([string]$t) Write-Host "  FALHA $t" -ForegroundColor Red; $script:falhas.Add($t) }
function Info  { param([string]$t) Write-Host "        $t" -ForegroundColor DarkGray }

# `-MaximumRedirection 0` faz o Invoke-WebRequest **lancar** no 3xx, em vez de
# seguir. E preciso ver o 301: seguir nao prova nada, porque o destino final
# seria identico. O `curl.exe` faz isto sem excecoes e ja vem no Windows 10+.
function Testar-Codigo {
    param([string]$Url)
    $saida = & curl.exe -s -o NUL -w '%{http_code}|%{redirect_url}' --max-time 25 $Url 2>$null
    $partes = "$saida".Split('|')
    return @{ Codigo = $partes[0]; Destino = if ($partes.Count -gt 1) { $partes[1] } else { '' } }
}

Write-Host ''
Write-Host "=== $Base ===" -ForegroundColor Cyan

# 1) healthz
$r = Testar-Codigo "$Base/healthz"
if ($r.Codigo -eq '200') { Ok "healthz responde 200" } else { Falha "healthz deu $($r.Codigo)" }

# 2) redireccionamento de /monitor para /monitor/
$semBarra = $Base.TrimEnd('/')
$r = Testar-Codigo $semBarra
if ($r.Codigo -eq '301' -and $r.Destino -match '/monitor/$') {
    Ok "$semBarra -> 301 para $($r.Destino)"
} else {
    Falha "$semBarra deu $($r.Codigo) e destino '$($r.Destino)' (esperado 301 para /monitor/)"
}

# 3) estaticos. Um 200 no healthz nao chega: se o `app.js` faltasse, a pagina
#    carregava e ficava em branco, sem nada a apontar para a causa.
foreach ($f in @('/', '/app.css', '/app.js')) {
    $dados = & curl.exe -s -w '|%{http_code}' --max-time 25 "$Base$f" 2>$null
    $codigo = "$dados".Substring("$dados".LastIndexOf('|') + 1)
    $tamanho = "$dados".Length - $codigo.Length - 1
    if ($codigo -eq '200' -and $tamanho -gt 500) {
        Ok "$f  $tamanho bytes"
    } else {
        Falha "$f devolveu $codigo com $tamanho bytes"
    }
}

# 4) sem sessao
$semSessao = & curl.exe -s -o NUL -w '%{http_code}' --max-time 25 "$Base/api/estado" 2>$null
if ($semSessao -eq '401') { Ok 'sem sessao, /api/estado responde 401' }
else { Falha "/api/estado sem sessao deu $semSessao (tinha de ser 401)" }

# 5) password errada
$mau = & curl.exe -s -o NUL -w '%{http_code}' --max-time 25 -X POST `
    -H 'Content-Type: application/json' -d '{"password":"nao-e-esta-de-certeza"}' "$Base/api/login" 2>$null
if ($mau -eq '401') { Ok 'password errada e recusada (401)' }
else { Falha "login com password errada deu $mau (tinha de ser 401)" }

# 6) password certa. O corpo vai num ficheiro temporario: passar a password numa
#    `-d` de linha de comando deixava-a no historico e na lista de processos.
$tmp = [IO.Path]::GetTempFileName()
try {
    # `ConvertTo-Json` e nao concatenacao de texto: uma password com aspas ou
    # barras partia o JSON, e o erro apareceria como "password incorreta" --
    # a mandar procurar o problema no sitio errado.
    [IO.File]::WriteAllText($tmp, (@{ password = $password } | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))

    $jar = Join-Path $env:TEMP 'iqos-monitor-cookies.txt'
    if (Test-Path $jar) { Remove-Item $jar -Force }

    $login = & curl.exe -s -o NUL -w '%{http_code}' --max-time 25 -X POST `
        -H 'Content-Type: application/json' --data-binary "@$tmp" `
        -c $jar "$Base/api/login" 2>$null
    if ($login -eq '200') { Ok 'login com a password certa' } else { Falha "login deu $login" }

    if ($login -eq '200') {
        $corpo = & curl.exe -s --max-time 30 -b $jar "$Base/api/estado" 2>$null
        try {
            $estado = $corpo | ConvertFrom-Json
            $servicos = @($estado.servicos)
            $imagens = @($estado.imagens)

            if ($servicos.Count -gt 0) { Ok "$($servicos.Count) servicos em /api/estado" }
            else { Falha 'nenhum servico em /api/estado' }

            if ($imagens.Count -gt 0) { Ok "$($imagens.Count) imagens em /api/estado" }
            else { Falha 'nenhuma imagem em /api/estado' }

            # Os nomes vem do `maquina()` do server.py: `memoria` e um objeto,
            # `carga` e uma lista de tres (1, 5 e 15 minutos). Vale a pena fixar
            # isto aqui -- se o painel mudar de forma, e este teste que avisa.
            if ($estado.maquina.memoria.total_mb) {
                Ok ("maquina: {0} MB ({1}% usada), carga {2}" -f `
                    $estado.maquina.memoria.total_mb, $estado.maquina.memoria.percentagem, $estado.maquina.carga[0])
            } else { Falha 'metricas da maquina em falta' }

            if ($estado.maquina.disco.total_gb) {
                Ok ("disco: {0} GB, {1}% usado" -f $estado.maquina.disco.total_gb, $estado.maquina.disco.percentagem)
            } else { Falha 'metricas de disco em falta' }

            # As sondas sao o que distingue "o contentor esta la" de "o servico
            # responde". Aqui so se confirma que vem preenchida.
            $comSonda = @($servicos | Where-Object { $_.sondas }).Count
            Ok "$comSonda de $($servicos.Count) servicos com sondas de porta"

            Info ("exemplo: {0} -- {1}" -f $servicos[0].nome, $servicos[0].estado)
        } catch {
            Falha "resposta de /api/estado nao e JSON valido: $($_.Exception.Message)"
        }
    }
} finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

Write-Host ''
if ($falhas.Count -eq 0) {
    Write-Host '  Painel validado.' -ForegroundColor Green
    Write-Host "  Entrar em: https://sabemos.studio/monitor/" -ForegroundColor Green
    Write-Host '  Password : deploy/kamatera/monitor-password.txt' -ForegroundColor DarkGray
    Write-Host ''
    exit 0
}
Write-Host "  $($falhas.Count) verificacoes falharam:" -ForegroundColor Red
foreach ($f in $falhas) { Write-Host "    - $f" -ForegroundColor Red }
Write-Host ''
exit 1
