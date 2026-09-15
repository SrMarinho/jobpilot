# Fonte unica de verdade das tarefas agendadas do JobPilot.
#
# Antes esse script cobria 4 tarefas e o resto era criado a mao. Autopost,
# Hired e Followup nunca chegaram a ser registrados: os XMLs existiam no repo,
# o comando da CLI era valido, e mesmo assim nao havia uma linha [autopost] em
# nenhum log. Se uma tarefa nao esta aqui, ela nao existe.
#
# Os triggers deixaram de ser LogonTrigger: com todos disparando no logon, as
# tarefas brigavam pelo browser lock, o apply segurava o browser por ~1h e o
# engage morria na fila. Agora cada uma tem sua janela.
#
# Rodar como Administrador:
#   powershell -ExecutionPolicy Bypass -File .local\reimport_tasks.ps1

$ErrorActionPreference = 'Continue'
$Local = 'F:\Documentos\Projetos\Code\jobpilot\.local'

# Nome antigo com hifen, criado a mao fora deste script.
$Legacy = @('JobPilot-Engage')

$Tasks = @(
    @{ Name = 'JobPilot Connect';  Xml = 'jobpilot_connect_task.xml'  }  # diario 08h
    @{ Name = 'JobPilot Report';   Xml = 'jobpilot_report_task.xml'   }  # segunda 08h30
    @{ Name = 'JobPilot Autopost'; Xml = 'jobpilot_autopost_task.xml' }  # ter/sex 09h
    @{ Name = 'JobPilot Hired';    Xml = 'jobpilot_hired_task.xml'    }  # sabado 10h
    @{ Name = 'JobPilot Apply';    Xml = 'jobpilot_task.xml'          }  # diario 12h
    @{ Name = 'JobPilot Engage';   Xml = 'jobpilot_engage_task.xml'   }  # diario 19h
    @{ Name = 'JobPilot Drain';    Xml = 'jobpilot_drain_task.xml'    }  # de hora em hora
)

foreach ($name in $Legacy) {
    schtasks /delete /tn $name /f 2>$null | Out-Null
}

foreach ($t in $Tasks) {
    $xml = Join-Path $Local $t.Xml
    if (-not (Test-Path $xml)) {
        Write-Host "SKIP $($t.Name): $xml nao existe"
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
