#requires -Version 5.1
<#
.SYNOPSIS
    Define a password de administrador do painel de estado do sistema.

.DESCRIPTION
    Escreve `MONITOR_PASSWORD` no `edge/.env` da VM. Essa e a unica fonte da
    password: o contentor `iqos-monitor` le-a do ambiente e o `edge/compose.yml`
    recusa arrancar sem ela (ver o comentario la).

    O ficheiro e actualizado por **leitura-modificacao-escrita**. Nao e um
    detalhe: o `edge/.env` guarda tambem o `ORIGEM_UPSTREAM`, escrito pelo
    `17-origem.ps1`. Escrever o ficheiro de raiz apagava a origem e o Caddy
    passava a servir o sitio do lado errado -- um estrago silencioso, porque o
    `.env` muda muito depois de o sitio se portar mal.

    A password e transportada em base64 (o mesmo canal do
    `00-push-edge-files.ps1`): atravessar PowerShell -> ssh -> bash come aspas e
    simbolos, e uma password com `$` ou `!` chegava truncada sem dar erro.

    NOTA: a password e escrita em `monitor-password.txt`, ao lado deste script,
    e nao no ecra. Os registos desta consola acabam em transcricoes e em
    historico de shell; um ficheiro ao lado do script fica onde e util e nao
    anda a viajar.

.PARAMETER Password
    Password a usar. Se for omitida, e gerada uma com 24 caracteres.

.PARAMETER Mostrar
    Escreve a password no ecra. So com pedido explicito.

.EXAMPLE
    .\18-monitor-env.ps1
    .\18-monitor-env.ps1 -Password 'a-minha-password-secreta'
    .\18-monitor-env.ps1 -Mostrar
#>
[CmdletBinding()]
param(
    [string]$Password,

    [switch]$Mostrar,

    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",
    [string]$EdgeDir = '/opt/iqos/edge',

    # Sem valor por omissao aqui. `$PSScriptRoot` ainda nao esta definido quando
    # o PowerShell avalia os valores por omissao dos parametros, por isso
    # `"$PSScriptRoot\monitor-password.txt"` dava `C:\monitor-password.txt` --
    # e o erro so aparecia depois de a password ja estar escrita na VM, a meio.
    # Fica resolvido em baixo, no corpo do script.
    [string]$FicheiroLocal
)

$ErrorActionPreference = 'Stop'

if (-not $FicheiroLocal) {
    $FicheiroLocal = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'monitor-password.txt'
}

if (-not $Password) {
    # Alfabeto sem `$`, `` ` ``, `"`, `'`, `\`, `#`, espaco nem `!`:
    #   - `#` e `$` sao interpretados pelo `docker compose` ao ler o `.env`;
    #   - `"` e `'` e `\` sao comidos ao atravessar PowerShell -> ssh -> bash;
    #   - `!` dispara a expansao de historico num shell interactivo.
    # 24 caracteres deste alfabeto (~51 simbolos) dao ~136 bits, muito acima do
    # que uma password de painel precisa.
    $alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_.'
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 24
    $rng.GetBytes($bytes)
    $Password = -join ($bytes | ForEach-Object { $alfabeto[$_ % $alfabeto.Length] })
    $rng.Dispose()
    Write-Host '  password gerada (24 caracteres)' -ForegroundColor DarkGray
}

if ($Password.Length -lt 12) { throw 'a password tem de ter pelo menos 12 caracteres.' }

# Um `#` na password nao parte o arranque -- parte a leitura: o `docker compose`
# trata o resto da linha como comentario e o servidor arranca com metade da
# password. Melhor recusar do que diagnosticar isso mais tarde.
if ($Password -match '[#\s"' + "'" + '`]') {
    throw 'a password nao pode conter #, espaco, aspas nem backtick -- ver a nota no script.'
}

Write-Host ''
Write-Host "=== A definir MONITOR_PASSWORD em $EdgeDir/.env ===" -ForegroundColor Cyan

# O que se codifica e a **linha inteira** (`CHAVE=valor`), e nao so o valor.
#
# A primeira versao codificava apenas a password e escrevia-a no `.env` sem
# chave nenhuma. Isso da duas coisas mas: o `docker compose` ignora a linha (nao
# tem `=`), a variavel nunca chega ao contentor, e o servidor morre logo no
# arranque -- de proposito, porque um painel sem password ficaria publico. O
# `linhas=3` na saida era a pista: as linhas soltas das tentativas anteriores
# nao eram apanhadas pelo `grep -v ^MONITOR_PASSWORD=`, porque nao comecavam
# pela chave. Acumulavam a cada execucao.
#
# Com a linha inteira no payload, o valor continua a nao aparecer no comando
# remoto (que e o objetivo do base64) e a chave fica sempre onde tem de estar.
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("MONITOR_PASSWORD=$Password"))

# `grep -v ^MONITOR_PASSWORD=`: tira o valor antigo.
# `printf %s ... | base64 -d`: escreve a linha `MONITOR_PASSWORD=...` sem
#            acrescentar nada.
# `echo >>`: o `base64 -d` nao poe mudanca de linha; sem isto a variavel juntava
#            -se a linha seguinte.
# `grep -c .`: conta as linhas, para confirmar que o ficheiro ficou inteiro sem
#              imprimir o conteudo (que mostraria a password).
#
# As partes com `$(...)` vao entre **plicas simples**, de proposito. O comando
# remoto e escrito aqui no PC antes de partir, e em PowerShell 5.1 um `$( )`
# dentro de aspas duplas e uma subexpressao que o PowerShell resolve **localmente**
# -- tentava correr `grep` e `echo` do Windows antes de haver ssh. Entre plicas,
# o `$( )` chega intacto a bash, que e quem o deve resolver. O `||` tambem nao
# existe em PowerShell 5.1, por isso nao se usa aqui para nada.
$remoto = 'cd ' + $EdgeDir + '; touch .env; grep -v ^MONITOR_PASSWORD= .env > .env.novo; ' +
"printf %s $b64 | base64 -d >> .env.novo; echo >> .env.novo; " +
'mv .env.novo .env; echo linhas=$(grep -c . .env); grep ^ORIGEM_UPSTREAM= .env; echo fim'

& ssh -i $SshKey -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR "$SshUser@$SshHost" $remoto
if ($LASTEXITCODE -ne 0) { throw "ssh falhou (exit $LASTEXITCODE)" }

# Copia de consulta. Fora da pasta `edge/` de proposito: o
# `00-push-edge-files.ps1` envia tudo o que esta em `edge/`, e esta password nao
# deve andar a ser reenviada em cada publicacao.
[IO.File]::WriteAllText($FicheiroLocal, $Password + "`n", [Text.UTF8Encoding]::new($false))
Write-Host ''
Write-Host "  password guardada em: $FicheiroLocal" -ForegroundColor Green
if ($Mostrar) { Write-Host "  password: $Password" -ForegroundColor Yellow }

Write-Host ''
Write-Host '=== A recriar o contentor do monitor ===' -ForegroundColor Cyan
# Sem `| tail`, sem `&&`: o `2>&1` ja ajunta os erros, e o comando e curto o
# suficiente para se ver tudo. Um `|` entre o PowerShell e o ssh e uma aspa a
# mais sao duas formas conhecidas de isto falhar em silencio.
& ssh -i $SshKey -o BatchMode=yes -o LogLevel=ERROR "$SshUser@$SshHost" `
    "cd $EdgeDir; docker compose up -d --build monitor 2>&1"
Write-Host ''
Write-Host '  para aplicar a rota nova no Caddy:  bash /opt/iqos/05-edge-up.sh' -ForegroundColor DarkGray
Write-Host '  para entrar:  https://sabemos.studio/monitor/' -ForegroundColor DarkGray
Write-Host ''
