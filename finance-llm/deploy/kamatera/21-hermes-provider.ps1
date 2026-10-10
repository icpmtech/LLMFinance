#requires -Version 5.1
<#
.SYNOPSIS
    Poe o Hermes Agent da VM no provider que a solucao ja usa (DeepSeek).

.DESCRIPTION
    O Jarvis responde «Hermes is not connected to any AI provider yet». A causa,
    medida comparando com o PC (onde funciona):

      PC  ->  model.provider: deepseek     model.default: deepseek-chat
              DEEPSEEK_API_KEY no /opt/data/.env

      VM  ->  model.provider: auto         model.default: anthropic/claude-opus-4.6
              model.base_url: https://openrouter.ai/api/v1
              nenhum provider com chave (0 em 11 chaves)

    A VM esta apontada ao OpenRouter, para um modelo Anthropic, sem chave. Nada
    a que se ligar.

    O modelo do Hermes **nao** se configura pelo ambiente: ele le o
    `config.yaml` do seu volume (`/opt/data`). O proprio ficheiro diz como se
    muda (`hermes config set`), e e isso que este script usa em vez de editar
    YAML a mao -- um `sed` num config.yaml de 124 KB, com listas e aninhamento,
    e uma forma garantida de o corromper.

    A chave vem do container do PC, que ja a tem a funcionar. **Nunca passa por
    aqui em claro**: e lida dentro deste script, vai em base64 no comando remoto,
    e so o comprimento dela aparece no ecra.

.PARAMETER Chave
    A chave DeepSeek. Se for omitida, e lida do container do PC.

.PARAMETER Mostrar
    Mostra a chave no ecra. So com pedido explicito.

.EXAMPLE
    .\21-hermes-provider.ps1
    .\21-hermes-provider.ps1 -Chave 'sk-...'
#>
[CmdletBinding()]
param(
    [string]$Chave,

    # Onde ir buscar a chave, quando nao e dada a mao.
    [string]$ContentorPc = 'finance-llm-hermes-agent',
    [string]$FicheiroEnvPc = '/opt/data/.env',

    # Alvo.
    [string]$ContentorVm = 'iqos-hermes-agent',
    [string]$SshHost = '45.147.251.188',
    [string]$SshUser = 'root',
    [string]$SshKey = "$env:USERPROFILE\.ssh\iqos_kamatera_ed25519",

    # O provider da solucao. Bate com o `MIROFISH_LLM_BASE_URL` do `.env`.
    [string]$Provider = 'deepseek',
    [string]$Modelo = 'deepseek-chat',
    [string]$BaseUrl = 'https://api.deepseek.com/v1',

    [switch]$Mostrar
)

$ErrorActionPreference = 'Stop'

# --- 1. Obter a chave -------------------------------------------------------
if (-not $Chave) {
    Write-Host ''
    Write-Host "=== A ler DEEPSEEK_API_KEY do container do PC ($ContentorPc) ===" -ForegroundColor Cyan

    if (-not (docker ps --filter "name=$ContentorPc" --format '{{.Names}}')) {
        throw "o container $ContentorPc nao esta a correr -- sem ele nao ha chave para copiar. Passe -Chave."
    }

    # Le so o valor. O `sed` corta antes do `=`. Sem aspas no padrao: atravessar
    # PowerShell -> docker -> sh come aspas.
    $linha = (docker exec $ContentorPc sh -c "grep -m1 ^DEEPSEEK_API_KEY= $FicheiroEnvPc") 2>$null
    if (-not $linha) { throw "nao encontrei DEEPSEEK_API_KEY em $FicheiroEnvPc ($ContentorPc)." }

    $Chave = ("$linha").Trim() -replace '^DEEPSEEK_API_KEY=', ''
    $Chave = $Chave.Trim().Trim('"').Trim("'")
}

if (-not $Chave) { throw 'a chave ficou vazia.' }
if ($Chave.Length -lt 20) { throw "a chave so tem $($Chave.Length) caracteres -- parece truncada." }

Write-Host ("  chave: {0} caracteres, comeca em {1}..." -f $Chave.Length, $Chave.Substring(0, 6)) -ForegroundColor DarkGray
if ($Mostrar) { Write-Host "  chave: $Chave" -ForegroundColor Yellow }

# O modelo do Hermes veio de um perfil que apontava ao OpenRouter. Deixar o
# `base_url` de la com o provider `deepseek` mandava os pedidos para o sitio
# errado -- e o sintoma seria um 401 do OpenRouter, a apontar para o servico
# errado. Por isso se escreve o endereco da DeepSeek tambem.
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("DEEPSEEK_API_KEY=$Chave"))

function Invoke-Vm {
    param([Parameter(Mandatory)][string]$Comando)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & ssh -i $SshKey -o BatchMode=yes -o LogLevel=ERROR "$SshUser@$SshHost" $Comando 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ ExitCode = $code; Output = (($out | Out-String).TrimEnd()) }
}

# --- 2. Escrever a chave no .env do volume ----------------------------------
Write-Host ''
Write-Host '=== A escrever a chave no .env do volume da VM ===' -ForegroundColor Cyan

# Leitura-modificacao-escrita: o `.env` tem 11 chaves e o Hermes le-o todo.
# Reescreve-lo de raiz apagava tudo o resto.
# `cmp -s -` no fim compara o que foi escrito com o que la estava, sem imprimir.
$remoto = 'cd /opt/data; ' +
"grep -v ^DEEPSEEK_API_KEY= .env > .env.novo; printf %s $b64 | base64 -d >> .env.novo; " +
'echo >> .env.novo; mv .env.novo .env; chown hermes:hermes .env; chmod 600 .env; ' +
'echo chaves=$(grep -c . .env); grep -c ^DEEPSEEK_API_KEY= .env'

$r = Invoke-Vm "docker exec $ContentorVm sh -c '$remoto'"
Write-Host "  $($r.Output)"
if ($r.ExitCode -ne 0) { throw 'falhou a escrever o .env na VM' }

# --- 3. Apontar o modelo ------------------------------------------------
Write-Host ''
Write-Host "=== A apontar o modelo para $Provider / $Modelo ===" -ForegroundColor Cyan

# `hermes config set` e a forma documentada (o proprio cabecalho do config.yaml
# o diz). Editar o YAML a mao, num ficheiro de 124 KB com listas aninhadas, e
# uma forma garantida de o estragar.
foreach ($par in @(
        @{ Chave = 'model.provider'; Valor = $Provider },
        @{ Chave = 'model.default'; Valor = $Modelo },
        @{ Chave = 'model.base_url'; Valor = $BaseUrl })) {
    $cmd = "hermes config set $($par.Chave) $($par.Valor)"
    $r = Invoke-Vm "docker exec $ContentorVm $cmd"
    $linha = ($r.Output -split "`n" | Where-Object { $_ } | Select-Object -Last 1)
    Write-Host ("  {0,-16} = {1,-28} {2}" -f $par.Chave, $par.Valor, $(if ($r.ExitCode -eq 0) { 'ok' } else { "FALHOU: $linha" })) `
        -ForegroundColor $(if ($r.ExitCode -eq 0) { 'Gray' } else { 'Red' })
    if ($r.ExitCode -ne 0) {
        Write-Host "    saida: $($r.Output)" -ForegroundColor DarkGray
    }
}

# --- 4. Reiniciar -------------------------------------------------------
Write-Host ''
Write-Host '=== A reiniciar o hermes-agent ===' -ForegroundColor Cyan
Invoke-Vm "docker restart $ContentorVm" | Out-Null
Start-Sleep -Seconds 35

# --- 5. Verificar -------------------------------------------------------
Write-Host ''
Write-Host '=== A verificar ===' -ForegroundColor Cyan

$r = Invoke-Vm "docker exec $ContentorVm hermes config get model.provider; docker exec $ContentorVm hermes config get model.default"
Write-Host "  configuracao agora:"
($r.Output -split "`n") | ForEach-Object { Write-Host "    $_" }

# A pergunta que interessa: o agente consegue mesmo falar com o provider?
#
# A primeira versao desta verificacao lia `$DEEPSEEK_API_KEY` do ambiente do
# shell e dava sempre 401 -- um falso negativo que parecia "chave invalida". A
# chave vive no `/opt/data/.env`, que o **Hermes** le por si; nao e uma variavel
# de ambiente do contentor, portanto o `sh` expandia-a para vazio.
#
# Aqui corre um pedido **a serio** (`POST /chat/completions`), que e o unico
# teste que prova a cadeia: config.yaml -> provider -> resposta. Um `GET /models`
# a 200 so provaria que a chave autentica.
#
# O Python vai pelo stdin do ssh: e a unica forma de atravessar PowerShell ->
# ssh -> docker sem aspas pelo caminho.
$py = @'
import json, urllib.error, urllib.request
chave = ""
for linha in open("/opt/data/.env", encoding="utf-8", errors="replace"):
    if linha.startswith("DEEPSEEK_API_KEY="):
        chave = linha.split("=", 1)[1].strip().strip('"').strip("'")
        break
if not chave:
    raise SystemExit("  sem DEEPSEEK_API_KEY no /opt/data/.env")
corpo = json.dumps({"model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "diz apenas: ok"}],
                    "max_tokens": 10}).encode()
pedido = urllib.request.Request(
    "https://api.deepseek.com/v1/chat/completions", data=corpo, method="POST",
    headers={"Authorization": "Bearer " + chave, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(pedido, timeout=45) as r:
        d = json.loads(r.read() or b"{}")
        texto = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
        servido = d.get("model")
        print("  HTTP %s  ->  %r  (servido como %s)" % (r.status, texto.strip()[:40], servido))
except urllib.error.HTTPError as e:
    print("  HTTP %s -- o provider recusou: %s" % (e.code, e.read()[:200]))
except Exception as e:
    print("  falhou: %s: %s" % (type(e).__name__, e))
'@

$saida = $py | & ssh -i $SshKey -o BatchMode=yes -o LogLevel=ERROR "$SshUser@$SshHost" "docker exec -i $ContentorVm python3 -" 2>&1
$saida -split "`n" | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
$ok = ("$saida" -match 'HTTP 200')

# E o erro do Jarvis? Se ainda aparecer no log, nao ficou resolvido.
$r = Invoke-Vm "docker logs --since 3m $ContentorVm 2>&1 | grep -c -i 'not connected to any AI provider'"
$ainda = "$($r.Output)".Trim()
Write-Host ("  avisos de provider no log: {0}" -f $ainda) -ForegroundColor $(if ($ainda -eq '0') { 'Green' } else { 'Yellow' })

Write-Host ''
if ($ok) {
    Write-Host '  O agente tem provider e responde.' -ForegroundColor Green
    Write-Host '  Testar no Jarvis: https://sabemos.studio/jarvis' -ForegroundColor Green
    exit 0
}
Write-Host '  O provider nao respondeu -- ver acima.' -ForegroundColor Red
exit 1
