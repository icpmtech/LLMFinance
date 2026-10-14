#requires -Version 5.1
<#
.SYNOPSIS
    Migra um servico do IQ OS para a VM do edge, um de cada vez.

.DESCRIPTION
    Cada servico vive em `servicos/<nome>/compose.yml` e arranca como projeto
    Docker proprio em `/opt/iqos/servicos/<nome>`. Consequencias:

      - `docker compose up` ali dentro so mexe nos contentores daquele projeto;
      - o Caddy, a landing, o Elasticsearch e o tunel nunca sao tocados;
      - o stack do PC nao e tocado (nada aqui lhe toca);
      - a porta de cada servico fica presa a 127.0.0.1 na VM.

    Os ficheiros de configuracao que cada servico precisa estao declarados em
    `$SERVICOS`, para nao duplicar no repositorio o que ja existe (`docker/<x>`).

.EXAMPLE
    .\14-servico-vm.ps1 -Listar
    .\14-servico-vm.ps1 -Nome searxng
    .\14-servico-vm.ps1 -Nome searxng -Logs
    .\14-servico-vm.ps1 -Nome searxng -Parar
#>
[CmdletBinding(DefaultParameterSetName = 'Aplicar')]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel',
    [string]$BaseDir = '/opt/iqos/servicos',

    [Parameter(ParameterSetName = 'Aplicar')]
    [string]$Nome,

    [Parameter(ParameterSetName = 'Listar')]
    [switch]$Listar,

    [Parameter(ParameterSetName = 'Aplicar')]
    [switch]$Logs,

    [Parameter(ParameterSetName = 'Aplicar')]
    [switch]$Parar
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$servicosDir = Join-Path $here 'servicos'
$raiz = Join-Path $here '..\..'   # finance-llm/

# Cada servico: porta local na VM, ficheiros de configuracao a enviar, e o
# caminho a sondar para validar. Acrescentar aqui ao migrar o proximo.
#
# `SondaTipo` distingue as duas formas de validar: `http` (o normal, sonda-se o
# caminho e espera-se 2xx/3xx/4xx) e `smtp` (o mailserver nao tem HTTP nenhum:
# le-se o banner do Postfix na porta de submissao).
$SERVICOS = @{
    'searxng' = @{
        Porta = 8888
        Sonda = '/'
        Extra = @(
            @{ Local = (Join-Path $raiz 'docker\searxng\settings.yml')
               Remote = "$BaseDir/searxng/etc/settings.yml" }
        )
    }
    'n8n' = @{
        Porta = 5678
        Sonda = '/healthz'
        Extra = @(
            @{ Local = (Join-Path $raiz 'docker\n8n\LEIA-ME.md')
               Remote = "$BaseDir/n8n/files/LEIA-ME.md" }
        )
    }
    # A imagem deste e construida localmente: transferir primeiro com
    # `15-imagem-vm.ps1 -Imagem iq-os-frontend:latest`.
    'frontend' = @{
        Porta = 4180
        Sonda = '/'
        Extra = @()
    }
    # Imagem publica (pull direto). O dashboard fica na 9119, que o compose local
    # nao publica -- aqui valida-se a 8642 (API OpenAI-compatavel do gateway).
    'hermes-agent' = @{
        Porta = 8642
        Sonda = '/health'
        Extra = @(
            @{ Local = (Join-Path $raiz 'docker\hermes\init\026-enable-iqos-plugin.sh')
               Remote = "$BaseDir/hermes-agent/config/init/026-enable-iqos-plugin.sh" }
            @{ Local = (Join-Path $raiz 'docker\hermes\plugins\dashboard-auth-iqos\plugin.yaml')
               Remote = "$BaseDir/hermes-agent/config/plugins/dashboard-auth-iqos/plugin.yaml" }
            @{ Local = (Join-Path $raiz 'docker\hermes\plugins\dashboard-auth-iqos\__init__.py')
               Remote = "$BaseDir/hermes-agent/config/plugins/dashboard-auth-iqos/__init__.py" }
            @{ Local = (Join-Path $raiz 'docker\hermes\skills\iqos\pesquisa-total\SKILL.md')
               Remote = "$BaseDir/hermes-agent/config/skills/iqos/pesquisa-total/SKILL.md" }
            @{ Local = (Join-Path $raiz 'docker\hermes\skills\iqos\pesquisa-profunda\SKILL.md')
               Remote = "$BaseDir/hermes-agent/config/skills/iqos/pesquisa-profunda/SKILL.md" }
            @{ Local = (Join-Path $raiz 'docker\hermes\skills\iqos\websearch\SKILL.md')
               Remote = "$BaseDir/hermes-agent/config/skills/iqos/websearch/SKILL.md" }
        )
    }
    # Stack autonoma de 6 contentores. As duas imagens construidas localmente
    # sao pequenas -- transferir primeiro com:
    #   .\15-imagem-vm.ps1 -Imagem iq-os-osif-backend:latest
    #   .\15-imagem-vm.ps1 -Imagem iq-os-osif-frontend:latest
    'osif' = @{
        Porta = 6110
        Sonda = '/health'
        Extra = @()
    }
    # Nao tem imagem propria: reusa `iq-os-backend:latest`, por isso essa imagem
    # tem de estar na VM primeiro. Sonda por socket (o endpoint e JSON-RPC e um
    # GET simples daria 405).
    'mcp' = @{
        Porta = 8765
        Sonda = '/'
        Extra = @()
    }
    # Imagem construida localmente sobre a publica `ghcr.io/666ghj/mirofish`,
    # com codigo proprio por cima -- transferir primeiro com
    # `15-imagem-vm.ps1 -Imagem iq-os-mirofish:latest`.
    # O backend recusa arrancar sem `LLM_API_KEY` e `ZEP_API_KEY`; vem no `.env`.
    'mirofish' = @{
        Porta = 5001
        Sonda = '/health'
        Extra = @()
    }
    # A peca central: sem ele o modo `vm` serve a SPA mas `/api` da 502.
    # `data/`, `model/` e `logs/` ficam vazios de proposito. O `rag/` **nao**
    # pode ser montado: e codigo dentro da imagem, e tapá-lo mata o arranque.
    'backend' = @{
        # Fixa em 8002 no `compose.yml`, e nao herdada do `FINANCE_API_PORT`
        # do `.env` do PC. Ver o cabecalho desse ficheiro.
        Porta = 8002
        Sonda = '/health'
        Extra = @()
    }
    # Remetente do email transacional (Docker Mailserver). Sem sonda HTTP: a
    # `SondaTipo` muda-a para o banner do Postfix na porta de submissao.
    #
    # O primeiro arranque nao chega para enviar: falta a chave DKIM e a conta de
    # envio, ambas criadas a mao depois (`setup config dkim`, `setup email add`)
    # -- e falta o resto do DNS. Ver o README.
    #
    # Nao envia o `./config` inteiro: as chaves DKIM e o `postfix-accounts.cf`
    # sao gerados **na VM** e ficam la. O que vem do repositorio e so a afinacao
    # do Postfix.
    'mailserver' = @{
        Porta = 587
        Sonda = $null
        SondaTipo = 'smtp'
        Extra = @(
            @{ Local = (Join-Path $here 'servicos\mailserver\config\postfix-main.cf')
               Remote = "$BaseDir/mailserver/config/postfix-main.cf" }
        )
    }
}

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
            -o ConnectTimeout=10 -o LogLevel=ERROR "$SshUser@$SshHost" $RemoteCommand 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

function Show-Vm {
    param([Parameter(Mandatory)][string]$RemoteCommand)
    $r = Invoke-Vm $RemoteCommand
    if ($r.Output) { $r.Output -split "`n" | ForEach-Object { Write-Host "  $_" } }
    return $r
}

# Sonda de vida do servico. Duas formas, porque ha servicos que nao falam HTTP:
#
#   * `http` (o normal) -- le o codigo de estado do caminho declarado;
#   * `smtp` -- le o banner do Postfix na porta de submissao.
#
# No caso do SMTP o stdin vai de `/dev/null` de proposito: assim que o `nc` liga
# e o stdin fecha, a ligacao cai logo a seguir ao banner. Se em vez disso se
# escrevesse `QUIT` no pipe, o pedido chegava antes do `nc` ler o banner e o
# Postfix respondia `554 5.5.0 Error: SMTP protocol synchronization` -- uma sonda
# a dizer que o servico esta morto quando ele esta bom.
function Get-Sonda {
    param([Parameter(Mandatory)][hashtable]$Cfg)
    if ($Cfg.SondaTipo -eq 'smtp') {
        return (Invoke-Vm "nc -w 5 127.0.0.1:$($Cfg.Porta) < /dev/null").Output.Trim()
    }
    return (Invoke-Vm "curl -s -o /dev/null -m 5 -w %{http_code} http://127.0.0.1:$($Cfg.Porta)$($Cfg.Sonda)").Output.Trim()
}

function Send-VmFile {
    param([Parameter(Mandatory)][string]$Local, [Parameter(Mandatory)][string]$Remote)
    if (-not (Test-Path $Local)) { throw "nao encontro $Local" }
    # Caminho remoto sem espacos nem aspas: e o que permite nao ter de lutar com
    # o PowerShell, que come as aspas dos comandos nativos.
    if ($Remote -match '\s') { throw "caminho remoto com espacos nao suportado: $Remote" }
    $pai = $Remote.Substring(0, $Remote.LastIndexOf('/'))
    # Por stdin: sem limite de tamanho e sem aspas dentro do comando remoto.
    (Get-Content -Raw $Local) -replace "`r`n", "`n" | docker exec -i $TunnelContainer `
        ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 -o LogLevel=ERROR `
        "$SshUser@$SshHost" "mkdir -p $pai && cat > $Remote"
    if ($LASTEXITCODE -ne 0) { throw "falhou o envio de $Remote" }
    # O PowerShell injecta CR ao escrever em pipeline nativa.
    Invoke-Vm "sed -i 's/\r`$//' $Remote" | Out-Null
    # **Bit de execucao.** Sem isto um script de init (`/etc/cont-init.d/*.sh`) e
    # ignorado em silencio pelo s6 -- foi o que deixou o dashboard do Hermes sem
    # o plugin de autenticacao, e sem provider ele recusa ligar-se a 0.0.0.0.
    if ($Remote -match '\.sh$') {
        Invoke-Vm "chmod +x $Remote" | Out-Null
    }
    $tam = (Invoke-Vm "wc -c < $Remote").Output.Trim()
    $perms = (Invoke-Vm "stat -c %A $Remote").Output.Trim()
    Write-Host "  $Remote  ($tam bytes, $perms)"
}

if ($Listar) {
    Write-Host ''
    Write-Host 'Servicos disponiveis em servicos/:' -ForegroundColor Cyan
    foreach ($k in $SERVICOS.Keys | Sort-Object) {
        $porta = $SERVICOS[$k].Porta
        $sonda = if ($SERVICOS[$k].SondaTipo -eq 'smtp') { 'banner SMTP' } else { 'HTTP' }
        Write-Host ("  {0,-12} porta 127.0.0.1:{1,-5} sonda {2}" -f $k, $porta, $sonda)
    }
    Write-Host ''
    Write-Host '  Nota: o mailserver publica tambem a 25 em 0.0.0.0 (e por onde recebe' -ForegroundColor DarkGray
    Write-Host '  correio do mundo: o MX aponta para la).' -ForegroundColor DarkGray
    Write-Host ''
    return
}

if (-not $Nome) { throw 'indica -Nome <servico> (ou -Listar para ver as opcoes).' }

$cfg = $SERVICOS[$Nome]
if (-not $cfg) { throw "servico '$Nome' nao esta em `$SERVICOS`. Usa -Listar." }

$composeLocal = Join-Path $servicosDir "$Nome\compose.yml"
if (-not (Test-Path $composeLocal)) { throw "nao encontro $composeLocal" }

$remoteDir = "$BaseDir/$Nome"

if ($Logs) {
    & docker exec $TunnelContainer ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes `
        "$SshUser@$SshHost" "cd $remoteDir && docker compose logs -f --tail 60"
    return
}

if ($Parar) {
    Write-Host "a parar $Nome..." -ForegroundColor Cyan
    Show-Vm "cd $remoteDir && docker compose down" | Out-Null
    return
}

Write-Host ''
Write-Host "=== A migrar '$Nome' para a VM ===" -ForegroundColor Cyan
Write-Host "  destino: $remoteDir"
Write-Host ''
Write-Host '  Antes (VM):'
Show-Vm 'free -m | sed -n 2p; df -h / | tail -1' | Out-Null

Write-Host ''
Write-Host '=== 1. A enviar ficheiros ===' -ForegroundColor Cyan
Send-VmFile -Local $composeLocal -Remote "$remoteDir/compose.yml"
foreach ($f in $cfg.Extra) { Send-VmFile -Local $f.Local -Remote $f.Remote }
# O `.env` do repositorio tem as chaves (Hermes, MiroFish, TwoCaptcha...). Vai
# para o lado do compose, que e onde o `docker compose` o le para resolver os
# `${...}`. Fica fora do git (ver .gitignore) e so existe no PC e na VM.
$envLocal = Join-Path $raiz '.env'
if (Test-Path $envLocal) { Send-VmFile -Local $envLocal -Remote "$remoteDir/.env" }

Write-Host ''
Write-Host '=== 2. A arrancar ===' -ForegroundColor Cyan
Write-Host '  (projeto proprio: o edge, o ES e o tunel ficam intocados)'
# Rede partilhada: os servicos migrados tem de se resolver por nome entre si
# (o frontend precisa de ver o `backend`, o backend o `elasticsearch`). Como
# cada um e um projeto composes separado, sem isto cada um ficaria na sua rede.
Show-Vm 'docker network inspect iqos-net >/dev/null 2>&1 || docker network create iqos-net' | Out-Null
Show-Vm "cd $remoteDir && docker compose up -d 2>&1" | Out-Null

Write-Host ''
Write-Host '=== 3. A aguardar resposta ===' -ForegroundColor Cyan
# Valida por sonda propria e nao pelo healthcheck: nem todos os servicos do stack
# tem um (`servicos/*/compose.yml` pode nao definir `healthcheck`), e um
# healthcheck mal escrito faria isto esperar para sempre por um servico que esta
# bom. A sonda muda com o servico -- ver o `Get-Sonda`.
$vivo = $false
for ($i = 1; $i -le 24; $i++) {
    $estado = (Invoke-Vm "cd $remoteDir && docker compose ps --format '{{.Status}}'").Output
    $resposta = Get-Sonda -Cfg $cfg
    $ok = if ($cfg.SondaTipo -eq 'smtp') { $resposta -match '^220' } else { $resposta -match '^[234]' }
    if ($ok) {
        Write-Host "  respondeu '$resposta' na tentativa $i" -ForegroundColor Green
        $vivo = $true
        break
    }
    Write-Host "  tentativa $i : '$resposta' / $estado"
    Start-Sleep -Seconds 10
}
if (-not $vivo) {
    Write-Host '  NAO respondeu. Log:' -ForegroundColor Red
    Show-Vm "cd $remoteDir && docker compose logs --tail 30" | Out-Null
    throw "o servico '$Nome' nao arrancou."
}

Write-Host ''
Write-Host '=== 4. Validacao ===' -ForegroundColor Cyan
Show-Vm 'docker container ls --format table --filter name=iqos-' | Out-Null
Write-Host ''
if ($cfg.SondaTipo -eq 'smtp') {
    Write-Host "  sonda   banner SMTP em 127.0.0.1:$($cfg.Porta)"
    Write-Host "    $resposta  (220 = Postfix a responder)"
    Write-Host ''
    Write-Host '  certificado apresentado na submissao:' -ForegroundColor DarkGray
    Show-Vm "printf '' | openssl s_client -starttls smtp -connect 127.0.0.1:$($cfg.Porta) -servername mail.sabemos.studio 2>/dev/null | openssl x509 -noout -subject -issuer -dates" | Out-Null
} else {
    Write-Host "  sonda   http://127.0.0.1:$($cfg.Porta)$($cfg.Sonda)"
    Write-Host "    HTTP $resposta  (2xx/3xx/4xx provam que o servico esta vivo)"
}

Write-Host ''
Write-Host '  Depois (VM):'
Show-Vm 'free -m | sed -n 2p; df -h / | tail -1' | Out-Null
Write-Host ''
if ($cfg.SondaTipo -eq 'smtp') {
    Write-Host '  A porta 25 esta aberta a Internet de proposito (o MX aponta para la);' -ForegroundColor DarkGray
    Write-Host "  as restantes ($($cfg.Porta), 465, 993) so no loopback." -ForegroundColor DarkGray
    Write-Host '  Falta o DNS e o PTR, e a chave DKIM: ver o README desta pasta.' -ForegroundColor DarkGray
} else {
    Write-Host "  O servico escuta so em 127.0.0.1:$($cfg.Porta) -- nao esta exposto." -ForegroundColor DarkGray
}
Write-Host ''
