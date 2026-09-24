$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'

# Cadeia diaria unica: cada etapa so comeca quando a anterior termina.
#
# Antes eram seis tarefas com horario proprio e StartWhenAvailable. Com o PC
# desligado no horario, o Agendador disparava todas as perdidas no mesmo
# segundo do boot (apply, connect e engage as 21:02:40 do mesmo dia): o apply
# segurava o browser lock, o engage estourava a espera e morria na fila.
#
# Cada etapa chama o startup_* que ja existia, entao env de provider e retries
# continuam isolados por etapa. Falha de uma etapa nao interrompe as seguintes.
#
# Uma vez por dia: a tarefa dispara no logon E as 08h (o PC pode ficar ligado
# dias sem logon). Cada etapa concluida vai para daily_done.txt com a data de
# hoje e e pulada nos disparos seguintes do dia. Se o PC desligar no meio, o
# proximo logon retoma da etapa que faltou. Etapa que falhou tambem conta como
# feita: os scripts ja tem retry proprio, e repetir a cada logon so martelaria
# o LinkedIn.

$Local = 'F:\Documentos\Projetos\Code\jobpilot\.local'
$Day = (Get-Date).DayOfWeek
$Today = Get-Date -Format 'yyyy-MM-dd'
$DoneFile = Join-Path $Local 'daily_done.txt'

$done = @()
if (Test-Path $DoneFile) {
    $done = @(Get-Content $DoneFile | Where-Object { $_ -like "$Today *" })
}
# Reescreve so com as linhas de hoje: o arquivo nunca cresce.
Set-Content -Path $DoneFile -Value $done -Encoding ascii

# Ordem: report (sem browser, rapido) -> autopost (post cedo alcanca mais) ->
# connect -> apply (o mais longo) -> engage + metricas -> hired (semanal, por
# ultimo como antes).
$Steps = @(
    @{ Name = 'report';   Script = 'startup_report.bat';   Days = @('Monday') }
    @{ Name = 'autopost'; Script = 'startup_autopost.bat'; Days = @('Tuesday', 'Friday') }
    @{ Name = 'connect';  Script = 'startup_connect.bat';  Days = @() }
    @{ Name = 'apply';    Script = 'startup_apply.bat';    Days = @() }
    @{ Name = 'engage';   Script = 'startup_engage.bat';   Days = @() }
    @{ Name = 'hired';    Script = 'startup_hired.bat';    Days = @('Saturday') }
)

$failed = @()
foreach ($s in $Steps) {
    if ($s.Days.Count -gt 0 -and -not ($s.Days -contains "$Day")) {
        Write-Host "[daily] skip $($s.Name) (hoje e $Day)"
        continue
    }
    if ($done -contains "$Today $($s.Name)") {
        Write-Host "[daily] skip $($s.Name) (ja rodou hoje)"
        continue
    }
    $script = Join-Path $Local $s.Script
    Write-Host "[daily] $(Get-Date -Format 'HH:mm:ss') inicio $($s.Name)"
    & cmd.exe /c "`"$script`""
    $code = $LASTEXITCODE
    Write-Host "[daily] $(Get-Date -Format 'HH:mm:ss') fim $($s.Name) (exit $code)"
    Add-Content -Path $DoneFile -Value "$Today $($s.Name)" -Encoding ascii
    if ($code -ne 0) { $failed += $s.Name }
}

if ($failed.Count -gt 0) {
    Write-Host "[daily] etapas com falha: $($failed -join ', ')"
    exit 1
}
exit 0
