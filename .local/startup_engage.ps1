$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'

# Force local Ollama (DeepSeek sem saldo). Engage usa eval provider.
$env:LLM_PROVIDER = 'langchain'
$env:LLM_PROVIDER_EVAL = 'langchain'
$env:LANGCHAIN_BACKEND = 'ollama'
$env:LANGCHAIN_BACKEND_EVAL = 'ollama'
$env:LANGCHAIN_MODEL = 'qwen3:8b'
$env:LANGCHAIN_MODEL_EVAL = 'qwen3:8b'
$env:LANGCHAIN_BASE_URL = 'http://localhost:11434'

# Ensure Ollama is up (start hidden if needed)
$ollamaUp = $false
try {
    Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -TimeoutSec 3 -UseBasicParsing | Out-Null
    $ollamaUp = $true
} catch { $ollamaUp = $false }
if (-not $ollamaUp) {
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
    Start-Sleep -Seconds 8
}

$UvPath = 'C:\Users\Sr. Marinho\.local\bin\uv'
$MaxRetries = 5
$BaseDelay = 30

for ($i = 0; $i -lt $MaxRetries; $i++) {
    # posts-number=random sorteia entre --min-post e --max-post a cada run
    & $UvPath run main.py --headless engage --scheduled --posts-number random --min-post 1 --max-post 20
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
