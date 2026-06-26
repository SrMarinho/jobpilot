$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'

# Provider: Claude (Haiku por padrao) — qualidade muito acima do ollama local.
# Apenas no escopo do processo; nao altera o .env global.
$env:LLM_PROVIDER = 'claude'
$env:LLM_PROVIDER_EVAL = 'claude'

$UvPath = 'C:\Users\Sr. Marinho\.local\bin\uv'
$MaxRetries = 5
$BaseDelay = 30

for ($i = 0; $i -lt $MaxRetries; $i++) {
    # Orquestrador diario: skip se ja postou hoje; senao publica aprovado (FIFO),
    # avisa se so ha pendente, ou gera novo e manda p/ aprovacao se fila vazia.
    & $UvPath run main.py --headless content autopost --daily
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        exit 0
    }

    if ($i -lt ($MaxRetries - 1)) {
        $delay = [Math]::Pow(2, $i) * $BaseDelay
        Write-Host "autopost attempt $($i + 1) failed (exit $exitCode). Retrying in $delay s..."
        Start-Sleep -Seconds $delay
    }
}

Write-Host "autopost exhausted $MaxRetries retries."
exit 1
