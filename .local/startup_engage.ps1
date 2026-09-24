$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'

# DeepSeek (API remota). Engage usa eval provider.
# Apenas no escopo do processo; nao altera o .env global.
$env:LLM_PROVIDER = 'langchain'
$env:LLM_PROVIDER_EVAL = 'langchain'
$env:LANGCHAIN_BACKEND = 'deepseek'
$env:LANGCHAIN_BACKEND_EVAL = 'deepseek'
$env:LANGCHAIN_MODEL = 'deepseek-v4-flash'
$env:LANGCHAIN_MODEL_EVAL = 'deepseek-v4-flash'

$UvPath = 'C:\Users\Sr. Marinho\.local\bin\uv'
$MaxRetries = 5
$BaseDelay = 30

$engageExit = 1
for ($i = 0; $i -lt $MaxRetries; $i++) {
    # posts-number=random sorteia entre --min-post e --max-post a cada run
    & $UvPath run main.py --headless content engage --scheduled --posts-number random --min-post 1 --max-post 20
    $engageExit = $LASTEXITCODE

    if ($engageExit -eq 0) {
        break
    }

    if ($i -lt ($MaxRetries - 1)) {
        $delay = [Math]::Pow(2, $i) * $BaseDelay
        Write-Host "engage attempt $($i + 1) failed (exit $engageExit). Retrying in $delay s..."
        Start-Sleep -Seconds $delay
    }
}

if ($engageExit -ne 0) {
    Write-Host "engage exhausted $MaxRetries retries."
}

# Métricas (SSI + profile-views) sempre, mesmo se o engage falhou no meio —
# senão um crash de browser (TargetClosedError) pula a captura do dia.
& $UvPath run main.py --headless profile capture
$metricsExit = $LASTEXITCODE
if ($metricsExit -ne 0) {
    Write-Host "metrics failed (exit $metricsExit)."
}

exit $engageExit
