#requires -Version 5.1
<#
.SYNOPSIS
    Valida o setup completo do IQ OS na VM do edge.

.DESCRIPTION
    So leitura: nao arranca, nao para, nao altera nada. Verifica:

      1. que todos os contentores esperados existem e estao de pe;
      2. que cada servico responde na sua porta (sondando de dentro da VM);
      3. que os dados do Elasticsearch estao la (contagem de documentos);
      4. que nada esta exposto a Internet;
      5. o estado de RAM, swap e disco.

    Sai com codigo 1 se encontrar algum servico em falta ou sem resposta.

.EXAMPLE
    .\16-validar-setup.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$TunnelContainer = 'iqos-origin-tunnel'
)

$ErrorActionPreference = 'Stop'

# Servico -> contentor esperado, porta na VM, caminho a sondar.
# `Exposto` marca os que devem estar acessiveis de fora (80/443 no Caddy).
# `Tipo = 'smtp'` muda a sonda: o mailserver nao tem HTTP nenhum, le-se o banner
# do Postfix na porta de submissao.
$ESPERADO = @(
    @{ Nome = 'caddy (edge)';      Contentor = 'iqos-caddy';          Porta = $null; Sonda = $null }
    @{ Nome = 'landing';           Contentor = 'iqos-landing';        Porta = 8090;  Sonda = '/' }
    @{ Nome = 'elasticsearch';     Contentor = 'iqos-elasticsearch';  Porta = 9200;  Sonda = '/_cluster/health' }
    @{ Nome = 'searxng';           Contentor = 'iqos-searxng';        Porta = 8888;  Sonda = '/' }
    @{ Nome = 'n8n';               Contentor = 'iqos-n8n';            Porta = 5678;  Sonda = '/healthz' }
    @{ Nome = 'frontend (SPA)';    Contentor = 'iqos-frontend';       Porta = 4180;  Sonda = '/' }
    @{ Nome = 'hermes-agent';      Contentor = 'iqos-hermes-agent';   Porta = 8642;  Sonda = '/health' }
    @{ Nome = 'hermes dashboard';  Contentor = 'iqos-hermes-agent';   Porta = 9119;  Sonda = '/' }
    @{ Nome = 'mcp';               Contentor = 'iqos-mcp';            Porta = 8765;  Sonda = '/' }
    @{ Nome = 'osif-postgres';     Contentor = 'iqos-osif-postgres';  Porta = $null; Sonda = $null }
    @{ Nome = 'osif-redis';        Contentor = 'iqos-osif-redis';     Porta = $null; Sonda = $null }
    @{ Nome = 'osif-minio';        Contentor = 'iqos-osif-minio';     Porta = $null; Sonda = $null }
    @{ Nome = 'osif-backend';      Contentor = 'iqos-osif-backend';   Porta = 6110;  Sonda = '/health' }
    @{ Nome = 'osif-worker';       Contentor = 'iqos-osif-worker';    Porta = $null; Sonda = $null }
    @{ Nome = 'osif-frontend';     Contentor = 'iqos-osif-frontend';  Porta = 8894;  Sonda = '/' }
    @{ Nome = 'mailserver';        Contentor = 'iqos-mailserver';     Porta = 587;   Sonda = $null; Tipo = 'smtp' }
)

# Portas que NAO devem estar abertas a Internet. As do mailserver entram aqui
# com as excecoes que se explicam abaixo: a 25 (o MX aponta para la -- e por onde
# o mundo entrega correio) e a 993/587 (leitura e submissao autenticadas, para o
# stack do PC e para qualquer cliente de correio). A 465 (SMTPS) continua presa ao
# loopback: nao ha cliente nenhum a usa-la.
$NAO_EXPOR = @(9200, 9300, 8090, 8888, 5678, 4180, 8642, 9119, 6110, 9111, 8894, 8765, 5001, 465)

# Portas que devem estar acessiveis de fora (com a 22/80/443). A 25 e a 587
# precisam tambem da regra no firewall da Kamatera; a 993 tambem.
$ESPERADO_EXPOR = @(22, 80, 443, 25, 993, 587)

# Sondar estas a partir do PC nao prova nada: muitos ISP bloqueiam a saida para
# as portas de correio e o teste morre antes de sair. Falham aqui sem serem um
# problema -- ver a sonda de dentro da VM (seccao 2).
$NAO_CONCLUSIVA = @(25, 587)

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

if (-not (docker ps --filter "name=$TunnelContainer" --format '{{.Names}}')) {
    throw "o container $TunnelContainer nao esta a correr (ver 07-origin-tunnel.ps1)."
}

$problemas = 0

# --- 1. Contentores ---------------------------------------------------------
Write-Host ''
Write-Host '=== 1. Contentores ===' -ForegroundColor Cyan
# Duas chamadas separadas em vez de uma com `|` no format: o `|` nao vai
# citado para o shell remoto e seria interpretado como um pipe.
$ps = (Invoke-Vm 'docker ps -a --format {{.Names}}').Output
$status = (Invoke-Vm 'docker ps -a --format {{.Status}}').Output
if (-not $ps) { throw 'nao consegui listar os contentores.' }

$nomes = ($ps -split "`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$estados = ($status -split "`n") | ForEach-Object { $_.Trim() }
$estado = @{}
for ($i = 0; $i -lt $nomes.Count; $i++) {
    $estado[$nomes[$i]] = if ($i -lt $estados.Count) { $estados[$i] } else { '?' }
}

foreach ($s in $ESPERADO) {
    $c = $s.Contentor
    if (-not $estado.ContainsKey($c)) {
        Write-Host ("  {0,-32} {1}" -f $s.Nome, 'FALTA') -ForegroundColor Red
        $problemas++
        continue
    }
    $st = $estado[$c]
    $cor = if ($st -match '^Up' -and $st -notmatch 'unhealthy') { 'Green' } else { 'Red' }
    Write-Host ("  {0,-32} {1}" -f $s.Nome, $st) -ForegroundColor $cor
    if ($cor -eq 'Red') { $problemas++ }
}

# --- 2. Resposta de cada servico --------------------------------------------
Write-Host ''
Write-Host '=== 2. Resposta de cada servico (de dentro da VM) ===' -ForegroundColor Cyan
foreach ($s in $ESPERADO) {
    if (-not $s.Porta) { continue }
    if ($s.Tipo -eq 'smtp') {
        # Banner do Postfix. O stdin vai de `/dev/null`: a ligacao cai logo depois
        # do banner. (Escrever `QUIT` no pipe dava `554 ... SMTP protocol
        # synchronization`, porque o pedido chega antes de o banner ser lido.) A
        # porta vai separada por espaco -- o `nc` nao aceita `127.0.0.1:587`.
        $resposta = (Invoke-Vm "nc -w 5 127.0.0.1 $($s.Porta) < /dev/null").Output.Trim()
        $ok = $resposta -match '^220'
        if (-not $ok) { $problemas++ }
        $cor = if ($ok) { 'Green' } else { 'Red' }
        Write-Host ("  {0,-24} :{1,-6} {2}" -f $s.Nome, $s.Porta, $(if ($ok) { $resposta } else { "SEM BANNER ($resposta)" })) -ForegroundColor $cor
        continue
    }
    $cmd = "curl -s -o /dev/null -m 8 -w %{http_code} http://127.0.0.1:$($s.Porta)$($s.Sonda)"
    $codigo = (Invoke-Vm $cmd).Output.Trim()
    $ok = $codigo -match '^[234]'
    if (-not $ok) { $problemas++ }
    $cor = if ($ok) { 'Green' } else { 'Red' }
    Write-Host ("  {0,-24} :{1,-6} {2}" -f $s.Nome, $s.Porta, $(if ($ok) { "HTTP $codigo" } else { "SEM RESPOSTA ($codigo)" })) -ForegroundColor $cor
}

# O mailserver tem uma verificacao que os outros nao tem: o certificado. O
# backend valida o nome do host no handshake (`ssl.create_default_context`), e se
# estiver errado o envio **falha em silencio** -- fica so um aviso no log e a
# aprovacao de contas deixa de avisar o cliente. Aqui falha alto.
if ($estado.ContainsKey('iqos-mailserver')) {
    $assunto = (Invoke-Vm "printf '' | openssl s_client -starttls smtp -connect 127.0.0.1:587 -servername mail.sabemos.studio 2>/dev/null | openssl x509 -noout -subject").Output.Trim()
    $ok = $assunto -match 'mail\.sabemos\.studio'
    if (-not $ok) { $problemas++ }
    Write-Host ("  {0,-24} {1}" -f 'mailserver (TLS)', $(if ($ok) { "certificado: $assunto" } else { "CERTIFICADO ERRADO/NENHUM ($assunto)" })) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
}

# --- 3. Dados do Elasticsearch ----------------------------------------------
Write-Host ''
Write-Host '=== 3. Dados no Elasticsearch ===' -ForegroundColor Cyan
$docs = (Invoke-Vm 'curl -s http://127.0.0.1:9200/_cat/count?h=count').Output.Trim()
$idx = (Invoke-Vm 'curl -s http://127.0.0.1:9200/_cat/indices?h=index | wc -l').Output.Trim()
$saude = (Invoke-Vm 'curl -s http://127.0.0.1:9200/_cat/health?h=status').Output.Trim()
Write-Host "  documentos : $docs"
Write-Host "  indices    : $idx"
Write-Host "  estado     : $saude"
if ($docs -notmatch '^[0-9]+$' -or [int]$docs -eq 0) { $problemas++; Write-Host '  o indice esta vazio' -ForegroundColor Red }

# --- 4. Exposicao a Internet ------------------------------------------------
Write-Host ''
Write-Host '=== 4. Exposicao a Internet ===' -ForegroundColor Cyan
$aExp = @()
foreach ($p in $NAO_EXPOR) {
    $r = Test-NetConnection -ComputerName $SshHost -Port $p -WarningAction SilentlyContinue
    if ($r.TcpTestSucceeded) { $aExp += $p }
}
if ($aExp.Count -eq 0) {
    Write-Host '  nenhuma porta interna acessivel de fora' -ForegroundColor Green
} else {
    Write-Host ("  EXPOSTAS: {0}" -f ($aExp -join ', ')) -ForegroundColor Red
    $problemas++
}
foreach ($p in $ESPERADO_EXPOR) {
    $r = Test-NetConnection -ComputerName $SshHost -Port $p -WarningAction SilentlyContinue
    Write-Host ("  :{0,-4} {1}" -f $p, $(if ($r.TcpTestSucceeded) { 'aberta (esperado)' } else { 'FECHADA -- inesperado' })) -ForegroundColor $(if ($r.TcpTestSucceeded) { 'Gray' } else { 'Red' })
    # A 25 e a 587 falharem daqui nao prova nada: muitos ISP bloqueiam a saida
    # para as portas de correio, e o teste morre antes de sair do PC. Para
    # confirmar mesmo, ver de outra rede ou usar a sonda de dentro da VM (a
    # seccao 2). A 993 nao tem essa desculpa: se falhar, falta a regra no
    # firewall da Kamatera.
    if ($NAO_CONCLUSIVA -contains $p -and -not $r.TcpTestSucceeded) {
        Write-Host ("        (pode ser o ISP a bloquear a sua saida da {0}; ver a seccao 2)" -f $p) -ForegroundColor DarkGray
    }
}

# --- 5. Site publico --------------------------------------------------------
Write-Host ''
Write-Host '=== 5. Site publico ===' -ForegroundColor Cyan
foreach ($u in @('https://sabemos.studio/healthz', 'https://sabemos.studio/landing', 'https://sabemos.studio/api/health')) {
    try {
        $r = Invoke-WebRequest -Uri $u -TimeoutSec 20 -UseBasicParsing
        Write-Host ("  {0,-42} {1}" -f $u, "HTTP $($r.StatusCode)") -ForegroundColor Green
    } catch {
        Write-Host ("  {0,-42} {1}" -f $u, "FALHOU: $($_.Exception.Message)") -ForegroundColor Red
        $problemas++
    }
}

# --- 6. Recursos ------------------------------------------------------------
Write-Host ''
Write-Host '=== 6. Recursos da VM ===' -ForegroundColor Cyan
(Invoke-Vm 'free -m | sed -n 2,3p').Output -split "`n" | ForEach-Object { Write-Host "  $_" }
(Invoke-Vm 'df -h / | tail -1').Output -split "`n" | ForEach-Object { Write-Host "  $_" }
(Invoke-Vm 'nproc').Output -split "`n" | ForEach-Object { Write-Host "  vCPU: $_" }
(Invoke-Vm 'docker system df').Output -split "`n" | ForEach-Object { Write-Host "  $_" }

# --- Resumo -----------------------------------------------------------------
Write-Host ''
if ($problemas -eq 0) {
    Write-Host 'SETUP VALIDADO: todos os servicos de pe, a responder, sem exposicao indevida.' -ForegroundColor Green
} else {
    Write-Host "SETUP COM $problemas PROBLEMA(S) -- ver as linhas a vermelho acima." -ForegroundColor Red
}
Write-Host ''
if ($problemas -gt 0) { exit 1 }
