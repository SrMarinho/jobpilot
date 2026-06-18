$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'

$UvPath = 'C:\Users\Sr. Marinho\.local\bin\uv'
$MaxRetries = 5
$BaseDelay = 30

for ($i = 0; $i -lt $MaxRetries; $i++) {
    & $UvPath run main.py --headless engage --scheduled
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        exit 0
    }

    if ($i -lt ($MaxRetries - 1)) {
        $delay = [Math]::Pow(2, $i) * $BaseDelay
        Write-Host "engage attempt $($i + 1) failed (exit $exitCode). Retrying in $delay s..."
        Start-Sleep -Seconds $delay
    }
}

Write-Host "engage exhausted $MaxRetries retries."
exit 1
