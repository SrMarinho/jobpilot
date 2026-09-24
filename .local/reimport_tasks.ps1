# Fonte unica de verdade das tarefas agendadas do JobPilot.
#
# Antes esse script cobria 4 tarefas e o resto era criado a mao. Autopost,
# Hired e Followup nunca chegaram a ser registrados: os XMLs existiam no repo,
# o comando da CLI era valido, e mesmo assim nao havia uma linha [autopost] em
# nenhum log. Se uma tarefa nao esta aqui, ela nao existe.
#
# Os triggers deixaram de ser LogonTrigger: com todos disparando no logon, as
# tarefas brigavam pelo browser lock, o apply segurava o browser por ~1h e o
# engage morria na fila. Janelas por horario tambem nao bastaram: com
# StartWhenAvailable, PC desligado no horario fazia todas as perdidas
# dispararem juntas no boot. Agora tudo que usa browser e uma cadeia so
# (startup_daily.ps1), em sequencia; o drain segue a parte por nao usar browser.
#
# Rodar como Administrador:
#   powershell -ExecutionPolicy Bypass -File .local\reimport_tasks.ps1

$ErrorActionPreference = 'Continue'
$Local = 'F:\Documentos\Projetos\Code\jobpilot\.local'

# Sem elevacao o /delete falha calado e o /create seguinte devolve "arquivo ja
# existente" — sete paredes de vermelho que nao dizem o que realmente faltou.
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Este script precisa de Administrador.'
    Write-Host 'Abra o PowerShell como Admin e rode de novo:'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .local\reimport_tasks.ps1'
    exit 1
}

# Nomes antigos: o hifenizado criado a mao e as tarefas avulsas que viraram
# etapas da cadeia diaria.
$Legacy = @(
    'JobPilot-Engage',
    'JobPilot Connect',
    'JobPilot Report',
    'JobPilot Autopost',
    'JobPilot Hired',
    'JobPilot Apply',
    'JobPilot Engage'
)

$Tasks = @(
    @{ Name = 'JobPilot Daily'; Xml = 'jobpilot_daily_task.xml' }  # diario 08h, cadeia em sequencia
    @{ Name = 'JobPilot Drain'; Xml = 'jobpilot_drain_task.xml' }  # de hora em hora
)

foreach ($name in $Legacy) {
    schtasks /delete /tn $name /f 2>$null | Out-Null
}

# Um path quebrado dentro do <Arguments> registra a tarefa sem erro nenhum:
# schtasks devolve 0, a tarefa aparece no Agendador, e so no dia seguinte voce
# descobre que toda execucao terminou em exit 1 sem escrever uma linha de log,
# porque o wscript nunca achou o .vbs. Ja aconteceu: um "\r" no XML virou
# carriage return e ".local\run_hidden.vbs" virou ".local" + quebra de linha +
# "un_hidden.vbs". Por isso a validacao roda ANTES do registro.
function Test-TaskXmlPaths {
    param([string]$XmlPath)

    [xml]$doc = Get-Content -Raw -Path $XmlPath
    $ok = $true
    foreach ($exec in $doc.Task.Actions.Exec) {
        $raw = [string]$exec.Arguments
        if ($raw -match "[`r`n]") {
            Write-Host "  quebra de linha dentro de <Arguments> - path corrompido"
            $ok = $false
        }
        foreach ($m in [regex]::Matches($raw, '"([^"]+)"')) {
            $p = $m.Groups[1].Value
            if (-not (Test-Path -LiteralPath $p)) {
                Write-Host "  arquivo nao existe: $p"
                $ok = $false
            }
        }
    }
    return $ok
}

foreach ($t in $Tasks) {
    $xml = Join-Path $Local $t.Xml
    if (-not (Test-Path $xml)) {
        Write-Host "SKIP $($t.Name): $xml nao existe"
        continue
    }
    if (-not (Test-TaskXmlPaths $xml)) {
        Write-Host "SKIP $($t.Name): $($t.Xml) aponta para arquivo invalido"
        continue
    }
    schtasks /delete /tn $t.Name /f 2>$null | Out-Null
    schtasks /create /xml $xml /tn $t.Name
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FALHOU $($t.Name) (exit $LASTEXITCODE)"
    }
}

Write-Host ''
Write-Host '=== Tarefas JobPilot registradas ==='
Get-ScheduledTask | Where-Object { $_.TaskName -like '*JobPilot*' } |
    Select-Object TaskName, State | Format-Table -AutoSize
