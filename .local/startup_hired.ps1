$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
# Eval provider = Claude só p/ esta tarefa (extração de skills melhor que ollama
# local). Scoped ao processo — NÃO altera o .env global.
$env:LLM_PROVIDER_EVAL = 'claude'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'

& 'C:\Users\Sr. Marinho\.local\bin\uv' run main.py --headless jobs hired `
  --role 'Desenvolvedor de Software Pleno' `
  --days 90 `
  --max-profiles 10 `
  --gap `
  --trend `
  --telegram
